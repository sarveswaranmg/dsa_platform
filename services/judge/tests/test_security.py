"""Sandbox-escape suite.

Each test submits a hostile program and asserts the sandbox contains it — the
attack produces a benign verdict (RE/TLE/MLE/WA) and never damages the host,
leaks a secret, escapes the filesystem, or reaches the network. These are
standing assertions on the CLAUDE.md hard rules; if any starts failing, the
sandbox has regressed.
"""

import uuid

import pytest

from app.config import get_settings
from app.contracts import Language, Limits, SubmissionJob, TestCaseRef, Verdict
from app.runner import run
from tests.conftest import _Uploader

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_or_skip")]

CONTAINED = {Verdict.RE, Verdict.TLE, Verdict.MLE, Verdict.WA}


def _job(source: str, cases: list[TestCaseRef], *, time_ms: int = 3000,
         memory_mb: int = 256, output_bytes: int = 1_000_000) -> SubmissionJob:
    return SubmissionJob(
        submission_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        language=Language.PYTHON,
        source=source,
        limits=Limits(time_ms=time_ms, memory_mb=memory_mb, output_bytes=output_bytes),
        cases=cases,
    )


def _one_case(upload_case: _Uploader, expected: bytes = b"") -> list[TestCaseRef]:
    input_key, output_key = upload_case(b"", expected)
    return [TestCaseRef(ordinal=1, input_s3_key=input_key, expected_output_s3_key=output_key)]


def test_fork_bomb_is_contained(upload_case: _Uploader) -> None:
    # --pids-limit caps process creation; the worker wall-timeout guarantees
    # the call returns instead of hanging the host.
    src = "import os\nwhile True:\n    os.fork()\n"
    result = run(_job(src, _one_case(upload_case), time_ms=2000))
    assert result.cases[0].verdict in CONTAINED


def test_rootfs_write_blocked(upload_case: _Uploader) -> None:
    # --read-only rootfs: writing outside the /work tmpfs fails.
    src = "open('/pwned', 'w').write('x')\n"
    result = run(_job(src, _one_case(upload_case)))
    assert result.cases[0].verdict == Verdict.RE


def test_artifact_mount_is_read_only(upload_case: _Uploader) -> None:
    # /art (the built artifact) is mounted read-only during the run stage.
    src = "open('/art/pwned', 'w').write('x')\n"
    result = run(_job(src, _one_case(upload_case)))
    assert result.cases[0].verdict == Verdict.RE


def test_tmpfs_is_noexec(upload_case: _Uploader) -> None:
    # The one writable path (/work) is mounted noexec, so a dropped payload
    # cannot be executed.
    src = (
        "import os, subprocess\n"
        "open('/work/x.sh', 'w').write('#!/bin/sh\\necho pwned\\n')\n"
        "os.chmod('/work/x.sh', 0o755)\n"
        "subprocess.run(['/work/x.sh'], check=True)\n"
    )
    result = run(_job(src, _one_case(upload_case)))
    assert result.cases[0].verdict == Verdict.RE


def test_network_egress_blocked(upload_case: _Uploader) -> None:
    # --network none: no route off the box.
    src = (
        "import socket\n"
        "socket.setdefaulttimeout(3)\n"
        "socket.create_connection(('1.1.1.1', 53))\n"
    )
    result = run(_job(src, _one_case(upload_case)))
    assert result.cases[0].verdict == Verdict.RE


def test_no_secret_env_leak(upload_case: _Uploader) -> None:
    # The runner container inherits none of the judge/host environment; it
    # prints CLEAN (matching expected) only if no secret-shaped var is present.
    src = (
        "import os\n"
        "bad = [k for k in os.environ if any(s in k.upper() "
        "for s in ('SECRET', 'JWT', 'AWS', 'POSTGRES', 'PASSWORD', 'TOKEN'))]\n"
        "print('LEAK' if bad else 'CLEAN')\n"
    )
    result = run(_job(src, _one_case(upload_case, expected=b"CLEAN\n")))
    assert result.cases[0].verdict == Verdict.AC


def test_docker_socket_absent(upload_case: _Uploader) -> None:
    # The Docker socket is mounted into the trusted worker, never the runner.
    src = (
        "import os\n"
        "print('PRESENT' if os.path.exists('/var/run/docker.sock') else 'ABSENT')\n"
    )
    result = run(_job(src, _one_case(upload_case, expected=b"ABSENT\n")))
    assert result.cases[0].verdict == Verdict.AC


def test_huge_stdout_is_capped(upload_case: _Uploader) -> None:
    # The fsize ulimit + output truncation keep a stdout flood from filling
    # the tmpfs or the judge's memory; the attack ends in a benign verdict.
    src = "import sys\nwhile True:\n    sys.stdout.write('A' * 1_000_000)\n"
    result = run(_job(src, _one_case(upload_case), output_bytes=1_000_000))
    assert result.cases[0].verdict in {Verdict.RE, Verdict.WA}


@pytest.mark.usefixtures("runsc_or_skip")
def test_escape_suite_passes_under_gvisor_runtime(
    monkeypatch: pytest.MonkeyPatch, upload_case: _Uploader
) -> None:
    """Re-runs the sandbox-escape suite with JUDGE_RUNTIME=gvisor to prove the
    containment guarantees hold under gVisor too, not just runc."""
    monkeypatch.setenv("JUDGE_RUNTIME", "gvisor")
    get_settings.cache_clear()
    try:
        test_fork_bomb_is_contained(upload_case)
        test_rootfs_write_blocked(upload_case)
        test_artifact_mount_is_read_only(upload_case)
        test_tmpfs_is_noexec(upload_case)
        test_network_egress_blocked(upload_case)
        test_no_secret_env_leak(upload_case)
        test_docker_socket_absent(upload_case)
        test_huge_stdout_is_capped(upload_case)
    finally:
        get_settings.cache_clear()
