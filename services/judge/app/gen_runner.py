"""Differential-testing runner for judge-gen: compiles a reference and a
brute-force solution independently, then runs both against every generated
input and compares their outputs to EACH OTHER (never to a stored expected
value — there isn't one; that's the whole point of differential testing).

Reuses the exact same hardened container invocation as judge-live
(`app.exec_common`, itself built on `app.sandbox.build_run_command`) —
nothing about the security contract changes for this lane.
"""

import base64
import os
import shutil
import tempfile

from app import compare, s3
from app.config import get_settings
from app.contracts import Verdict
from app.exec_common import (
    SOURCE_FILENAME,
    ContainerOutcome,
    container_name,
    decode_output,
    image_for,
    run_container,
)
from app.gen_contracts import DiffCaseResult, DiffJob, DiffResult, DiffStatus
from app.sandbox import SandboxSpec

# Truncate captured disagreement output before it goes into a result message
# (and eventually ai's discard log) — full stress-case output could be large.
_DISAGREEMENT_OUTPUT_CAP = 2_000


def _classify_run(outcome: ContainerOutcome) -> tuple[Verdict, bytes | None]:
    """One side's run outcome, with no expected value to compare against —
    AC here just means "ran cleanly and produced output", not "correct"."""
    if outcome.killed_by_worker:
        return Verdict.TLE, None
    if outcome.envelope is None:
        if outcome.docker_returncode in (137, -9):
            return Verdict.MLE, None
        raise RuntimeError(
            f"gen runner container failed (rc={outcome.docker_returncode}): "
            f"{outcome.compile_log[:500]}"
        )
    env = outcome.envelope
    exit_code = int(env.get("exit_code", 0))
    if env.get("oom_killed") or exit_code == -9:
        return Verdict.MLE, None
    if env.get("timed_out"):
        return Verdict.TLE, None
    if exit_code != 0:
        return Verdict.RE, None
    if env.get("truncated"):
        return Verdict.RE, None  # can't trust a truncated output either way
    return Verdict.AC, decode_output(env)


def _truncated_b64(data: bytes | None) -> str | None:
    if data is None:
        return None
    return base64.b64encode(data[:_DISAGREEMENT_OUTPUT_CAP]).decode()


def _compile(
    *, job: DiffJob, source: str, workdir: str, role: str, runtime: str, wall_seconds: float
) -> ContainerOutcome:
    source_path = os.path.join(workdir, SOURCE_FILENAME[job.language])
    with open(source_path, "w") as fh:
        fh.write(source)
    os.chmod(source_path, 0o666)
    spec = SandboxSpec(
        image=image_for(job.language),
        argv=["compile", job.language.value],
        artifact_dir=workdir,
        memory_mb=max(job.limits.memory_mb, 512),
        pids_limit=job.limits.pids,
        name=container_name(job.job_id, f"gen-compile-{role}"),
        writable_artifact=True,
        output_bytes=job.limits.output_bytes,
        runtime=runtime,
    )
    return run_container(spec, stdin=b"", wall_seconds=wall_seconds)


def _run_one(
    *,
    job: DiffJob,
    workdir: str,
    role: str,
    ordinal: int,
    stdin: bytes,
    runtime: str,
    wall_seconds: float,
) -> ContainerOutcome:
    spec = SandboxSpec(
        image=image_for(job.language),
        argv=["run", job.language.value, str(job.limits.time_ms)],
        artifact_dir=workdir,
        memory_mb=job.limits.memory_mb,
        pids_limit=job.limits.pids,
        name=container_name(job.job_id, f"gen-run-{role}-{ordinal}"),
        writable_artifact=False,
        output_bytes=job.limits.output_bytes,
        env={"MAX_OUTPUT_BYTES": str(job.limits.output_bytes)},
        runtime=runtime,
    )
    return run_container(spec, stdin=stdin, wall_seconds=wall_seconds)


def run_diff(job: DiffJob) -> DiffResult:
    settings = get_settings()
    runtime = "runsc" if settings.judge_runtime == "gvisor" else "runc"
    os.makedirs(settings.scratch_root, exist_ok=True)
    ref_dir = tempfile.mkdtemp(prefix=f"{job.job_id.hex}-ref-", dir=settings.scratch_root)
    bf_dir = tempfile.mkdtemp(prefix=f"{job.job_id.hex}-bf-", dir=settings.scratch_root)
    os.chmod(ref_dir, 0o777)
    os.chmod(bf_dir, 0o777)
    compile_wall_seconds = settings.wall_grace_seconds + 20
    run_wall_seconds = job.limits.time_ms / 1000.0 + settings.wall_grace_seconds

    try:
        ref_compile = _compile(
            job=job, source=job.reference_source, workdir=ref_dir, role="ref",
            runtime=runtime, wall_seconds=compile_wall_seconds,
        )
        if ref_compile.killed_by_worker or ref_compile.docker_returncode != 0:
            return DiffResult(
                job_id=job.job_id, org_id=job.org_id, attempt=job.attempt,
                status=DiffStatus.REFERENCE_COMPILE_ERROR, agreement_pct=0.0,
                compile_error=ref_compile.compile_log[:4000] or "reference failed to compile",
                cases=[], request_id=job.request_id,
            )

        bf_compile = _compile(
            job=job, source=job.brute_force_source, workdir=bf_dir, role="bf",
            runtime=runtime, wall_seconds=compile_wall_seconds,
        )
        if bf_compile.killed_by_worker or bf_compile.docker_returncode != 0:
            return DiffResult(
                job_id=job.job_id, org_id=job.org_id, attempt=job.attempt,
                status=DiffStatus.BRUTE_FORCE_COMPILE_ERROR, agreement_pct=0.0,
                compile_error=bf_compile.compile_log[:4000] or "brute-force failed to compile",
                cases=[], request_id=job.request_id,
            )

        cases: list[DiffCaseResult] = []
        agree_count = 0
        for input_ref in job.inputs:
            stdin = s3.get_object(input_ref.input_s3_key, bucket=settings.ai_s3_bucket)

            ref_outcome = _run_one(
                job=job, workdir=ref_dir, role="ref", ordinal=input_ref.ordinal,
                stdin=stdin, runtime=runtime, wall_seconds=run_wall_seconds,
            )
            bf_outcome = _run_one(
                job=job, workdir=bf_dir, role="bf", ordinal=input_ref.ordinal,
                stdin=stdin, runtime=runtime, wall_seconds=run_wall_seconds,
            )
            ref_verdict, ref_output = _classify_run(ref_outcome)
            bf_verdict, bf_output = _classify_run(bf_outcome)

            agree = (
                ref_verdict == Verdict.AC
                and bf_verdict == Verdict.AC
                and ref_output is not None
                and bf_output is not None
                and compare.outputs_match(ref_output, bf_output, job.compare_mode)
            )
            if agree:
                agree_count += 1

            capture_reference = not agree or job.capture_agreement_outputs
            cases.append(
                DiffCaseResult(
                    ordinal=input_ref.ordinal,
                    agree=agree,
                    reference_verdict=ref_verdict,
                    brute_force_verdict=bf_verdict,
                    reference_output_b64=_truncated_b64(ref_output) if capture_reference else None,
                    brute_force_output_b64=None if agree else _truncated_b64(bf_output),
                )
            )

        agreement_pct = agree_count / len(job.inputs) if job.inputs else 0.0
        return DiffResult(
            job_id=job.job_id,
            org_id=job.org_id,
            attempt=job.attempt,
            status=DiffStatus.COMPLETED,
            agreement_pct=agreement_pct,
            cases=cases,
            request_id=job.request_id,
        )
    finally:
        shutil.rmtree(ref_dir, ignore_errors=True)
        shutil.rmtree(bf_dir, ignore_errors=True)
