"""The sandbox contract, in one place.

Every container that ever runs untrusted candidate code — whether it compiles
or executes — is launched through `build_run_command`. These flags are the
CLAUDE.md hard rules; they are NEVER relaxed to make a test pass. The unit
test in tests/test_sandbox.py asserts each one is present.

Two mount postures:
- compile: the per-submission artifact dir is mounted READ-WRITE so the
  compiler can emit its output there; everything else is still locked down.
- run: the same dir is mounted READ-ONLY (the built artifact); the program's
  only writable path is the /work tmpfs.
"""

from dataclasses import dataclass, field

# Fixed sandbox parameters (not caller-tunable — part of the contract).
WORK_DIR = "/work"
ARTIFACT_DIR = "/art"
TMPFS_SIZE = "64m"
NOFILE_LIMIT = 256
# nproc ulimit is a per-uid thread/proc ceiling; --pids-limit is the real
# fork-bomb gate, this is defense-in-depth.
NPROC_LIMIT = 256


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    argv: list[str]  # command executed inside the container
    artifact_dir: str  # host path holding source/artifact
    memory_mb: int
    pids_limit: int
    name: str  # so the runner can `docker kill` it on a worker-side timeout
    cpus: float = 1.0
    output_bytes: int = 1_000_000
    writable_artifact: bool = False  # True only for the compile stage
    env: dict[str, str] = field(default_factory=dict)
    runtime: str = "runc"  # "runc" (default) or "runsc" (gVisor)


def build_run_command(spec: SandboxSpec) -> list[str]:
    """Assemble the full `docker run` argv for one sandboxed execution."""
    mount_mode = "rw" if spec.writable_artifact else "ro"
    fsize_bytes = spec.output_bytes

    cmd: list[str] = [
        "docker",
        "run",
        "--rm",
        "--interactive",  # connect stdin so the program can read the test input
        "--name",
        spec.name,
        # --- isolation ---
        "--network",
        "none",  # no network egress
        "--read-only",  # read-only root filesystem
        # only writable path for a run container; noexec/nosuid/nodev, and
        # mode=1777 so the non-root uid can write here (default tmpfs is
        # root-owned 755)
        "--tmpfs",
        f"{WORK_DIR}:rw,noexec,nosuid,nodev,size={TMPFS_SIZE},mode=1777",
        # the built artifact / source; rw only while compiling
        "--volume",
        f"{spec.artifact_dir}:{ARTIFACT_DIR}:{mount_mode}",
        "--workdir",
        WORK_DIR,
    ]
    if spec.runtime != "runc":
        cmd += ["--runtime", spec.runtime]
    cmd += [
        # --- privilege ---
        "--user",
        "1000:1000",  # non-root (also baked into the image)
        "--cap-drop",
        "ALL",  # zero Linux capabilities
        "--security-opt",
        "no-new-privileges",  # block setuid escalation
        # --- resource limits ---
        "--pids-limit",
        str(spec.pids_limit),  # fork-bomb ceiling
        "--memory",
        f"{spec.memory_mb}m",  # hard RAM cap
        "--memory-swap",
        f"{spec.memory_mb}m",  # == memory ⇒ swap disabled, cap is real
        "--cpus",
        str(spec.cpus),  # CPU quota
        "--ulimit",
        f"fsize={fsize_bytes}:{fsize_bytes}",  # file/output size cap
        "--ulimit",
        f"nofile={NOFILE_LIMIT}:{NOFILE_LIMIT}",
        "--ulimit",
        f"nproc={NPROC_LIMIT}:{NPROC_LIMIT}",
    ]
    for key, value in spec.env.items():
        cmd += ["--env", f"{key}={value}"]
    cmd.append(spec.image)
    cmd += spec.argv
    return cmd
