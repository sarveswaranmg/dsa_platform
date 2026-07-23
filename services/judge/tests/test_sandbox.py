"""Guards the sandbox contract: every hardening flag must be present and no
stray mount may leak in. If a flag is ever dropped, this test fails — these
are the CLAUDE.md hard rules.
"""

from app.sandbox import ARTIFACT_DIR, WORK_DIR, SandboxSpec, build_run_command


def _spec(**overrides: object) -> SandboxSpec:
    base: dict[str, object] = {
        "image": "dsa-judge-python:3.12",
        "argv": ["run", "python", "2000"],
        "artifact_dir": "/scratch/sub-1",
        "memory_mb": 256,
        "pids_limit": 64,
        "name": "dsa-judge-test",
    }
    base.update(overrides)
    return SandboxSpec(**base)  # type: ignore[arg-type]


def _flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_all_hardening_flags_present() -> None:
    cmd = build_run_command(_spec())

    # no network
    assert "--network" in cmd and _flag_value(cmd, "--network") == "none"
    # read-only rootfs
    assert "--read-only" in cmd
    # writable scratch is tmpfs, noexec/nosuid/nodev
    tmpfs = _flag_value(cmd, "--tmpfs")
    assert tmpfs.startswith(f"{WORK_DIR}:")
    assert "noexec" in tmpfs and "nosuid" in tmpfs and "nodev" in tmpfs
    # non-root
    assert _flag_value(cmd, "--user") == "1000:1000"
    # no capabilities, no privilege escalation
    assert _flag_value(cmd, "--cap-drop") == "ALL"
    assert _flag_value(cmd, "--security-opt") == "no-new-privileges"
    # pids limit
    assert _flag_value(cmd, "--pids-limit") == "64"
    # memory cap with swap disabled (memory == memory-swap)
    assert _flag_value(cmd, "--memory") == "256m"
    assert _flag_value(cmd, "--memory-swap") == "256m"
    # cpu quota
    assert "--cpus" in cmd
    # output/file-size cap
    assert any(a.startswith("fsize=") for a in cmd)
    # ephemeral
    assert "--rm" in cmd


def test_run_stage_mounts_artifact_read_only() -> None:
    cmd = build_run_command(_spec(writable_artifact=False))
    mount = _flag_value(cmd, "--volume")
    assert mount == f"/scratch/sub-1:{ARTIFACT_DIR}:ro"


def test_compile_stage_mounts_artifact_read_write() -> None:
    cmd = build_run_command(_spec(writable_artifact=True))
    mount = _flag_value(cmd, "--volume")
    assert mount == f"/scratch/sub-1:{ARTIFACT_DIR}:rw"


def test_only_one_mount() -> None:
    # Exactly one --volume (the per-submission artifact dir) and one --tmpfs;
    # nothing else from the host is exposed to untrusted code.
    cmd = build_run_command(_spec())
    assert cmd.count("--volume") == 1
    assert cmd.count("--tmpfs") == 1


def test_memory_swap_always_equals_memory() -> None:
    cmd = build_run_command(_spec(memory_mb=512))
    assert _flag_value(cmd, "--memory") == _flag_value(cmd, "--memory-swap") == "512m"


def test_runtime_flag_present_for_gvisor() -> None:
    cmd = build_run_command(_spec(runtime="runsc"))
    assert "--runtime" in cmd and _flag_value(cmd, "--runtime") == "runsc"


def test_runtime_flag_absent_by_default() -> None:
    cmd = build_run_command(_spec())
    assert "--runtime" not in cmd
