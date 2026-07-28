"""Orchestrates one submission: compile once, then one sandboxed container per
test case, and turn each container's outcome into a verdict.

All untrusted execution goes through app.sandbox.build_run_command — the flags
there are the security contract.
"""

import os
import shutil
import tempfile

from app import compare, s3
from app.config import get_settings
from app.contracts import (
    CaseResult,
    SubmissionJob,
    SubmissionStatus,
    Verdict,
    VerdictMessage,
)
from app.exec_common import (
    SOURCE_FILENAME,
    ContainerOutcome,
    container_name,
    decode_output,
    image_for,
    run_container,
)
from app.sandbox import SandboxSpec


def _verdict_for_case(
    outcome: ContainerOutcome, expected: bytes, job: SubmissionJob
) -> CaseResult:
    limits = job.limits
    if outcome.killed_by_worker:
        return CaseResult(
            ordinal=0, verdict=Verdict.TLE, runtime_ms=limits.time_ms, memory_kb=0
        )
    # Container itself was OOM-killed (whole cgroup): no envelope, exit 137.
    if outcome.envelope is None:
        if outcome.docker_returncode in (137, -9):
            return CaseResult(
                ordinal=0, verdict=Verdict.MLE, runtime_ms=0, memory_kb=limits.memory_mb * 1024
            )
        raise RuntimeError(
            f"runner container failed (rc={outcome.docker_returncode}): {outcome.compile_log[:500]}"
        )

    env = outcome.envelope
    runtime_ms = int(env.get("time_ms", 0))
    memory_kb = int(env.get("memory_kb", 0))
    exit_code = int(env.get("exit_code", 0))

    if env.get("oom_killed") or exit_code == -9:
        verdict = Verdict.MLE
    elif env.get("timed_out"):
        verdict, runtime_ms = Verdict.TLE, limits.time_ms
    elif exit_code != 0:
        verdict = Verdict.RE
    elif env.get("truncated"):
        verdict = Verdict.WA  # output exceeded the cap; cannot be correct
    elif compare.outputs_match(decode_output(env), expected, job.compare_mode):
        verdict = Verdict.AC
    else:
        verdict = Verdict.WA
    return CaseResult(ordinal=0, verdict=verdict, runtime_ms=runtime_ms, memory_kb=memory_kb)


def _summary(cases: list[CaseResult]) -> Verdict:
    for case in cases:
        if case.verdict != Verdict.AC:
            return case.verdict
    return Verdict.AC


def run(job: SubmissionJob) -> VerdictMessage:
    settings = get_settings()
    runtime = "runsc" if settings.judge_runtime == "gvisor" else "runc"
    os.makedirs(settings.scratch_root, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix=f"{job.submission_id.hex}-", dir=settings.scratch_root)
    # World-accessible so uid 1000 inside the container can read/write during
    # compile and read during run; the dir is per-submission and ephemeral.
    os.chmod(workdir, 0o777)
    try:
        source_path = os.path.join(workdir, SOURCE_FILENAME[job.language])
        with open(source_path, "w") as fh:
            fh.write(job.source)
        os.chmod(source_path, 0o666)

        image = image_for(job.language)

        # --- compile stage (writable artifact mount) ---
        compile_spec = SandboxSpec(
            image=image,
            argv=["compile", job.language.value],
            artifact_dir=workdir,
            memory_mb=max(job.limits.memory_mb, 512),  # compilers are memory-hungry
            pids_limit=job.limits.pids,
            name=container_name(job.submission_id, "compile"),
            writable_artifact=True,
            output_bytes=job.limits.output_bytes,
            runtime=runtime,
        )
        compile_out = run_container(
            compile_spec, stdin=b"", wall_seconds=settings.wall_grace_seconds + 20
        )
        if compile_out.killed_by_worker or compile_out.docker_returncode != 0:
            return VerdictMessage(
                submission_id=job.submission_id,
                org_id=job.org_id,
                status=SubmissionStatus.COMPILE_ERROR,
                summary_verdict=Verdict.CE,
                compile_error=compile_out.compile_log[:4000] or "compilation failed",
                cases=[],
                request_id=job.request_id,
            )

        # --- run stage: one container per test case ---
        results: list[CaseResult] = []
        wall_seconds = job.limits.time_ms / 1000.0 + settings.wall_grace_seconds
        for case in job.cases:
            stdin = s3.get_object(case.input_s3_key)
            expected = s3.get_object(case.expected_output_s3_key)
            run_spec = SandboxSpec(
                image=image,
                argv=["run", job.language.value, str(job.limits.time_ms)],
                artifact_dir=workdir,
                memory_mb=job.limits.memory_mb,
                pids_limit=job.limits.pids,
                name=container_name(job.submission_id, f"run-{case.ordinal}"),
                writable_artifact=False,
                output_bytes=job.limits.output_bytes,
                env={"MAX_OUTPUT_BYTES": str(job.limits.output_bytes)},
                runtime=runtime,
            )
            outcome = run_container(run_spec, stdin=stdin, wall_seconds=wall_seconds)
            case_result = _verdict_for_case(outcome, expected, job)
            results.append(
                CaseResult(
                    ordinal=case.ordinal,
                    verdict=case_result.verdict,
                    runtime_ms=case_result.runtime_ms,
                    memory_kb=case_result.memory_kb,
                )
            )

        return VerdictMessage(
            submission_id=job.submission_id,
            org_id=job.org_id,
            status=SubmissionStatus.COMPLETED,
            summary_verdict=_summary(results),
            compile_error=None,
            cases=results,
            request_id=job.request_id,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
