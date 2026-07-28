"""Real sandboxed differential-testing runner test: reference vs. brute-force
solutions run against inputs fetched from the ai service's own S3 bucket,
compared to each other (never to a stored expected value). Requires the
Docker socket and localstack (both up under `make test`); skips cleanly
otherwise — same style as tests/test_pipeline_integration.py.
"""

import uuid

import pytest

from app.contracts import CompareMode, Language, Limits
from app.gen_contracts import DiffInputRef, DiffJob, DiffStatus
from app.gen_runner import run_diff
from tests.conftest import _GenInputUploader

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker_or_skip")]

CORRECT_PY = "a, b = map(int, input().split())\nprint(a + b)\n"
WRONG_PY = "a, b = map(int, input().split())\nprint(a * b)\n"
INVALID_PY = "def broken(:\n"


def _job(
    *,
    reference: str,
    brute_force: str,
    inputs: list[DiffInputRef],
    attempt: int = 1,
    capture_agreement_outputs: bool = False,
) -> DiffJob:
    return DiffJob(
        job_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        attempt=attempt,
        language=Language.PYTHON,
        reference_source=reference,
        brute_force_source=brute_force,
        limits=Limits(time_ms=3000, memory_mb=256),
        compare_mode=CompareMode.WHITESPACE,
        inputs=inputs,
        capture_agreement_outputs=capture_agreement_outputs,
    )


def test_agreeing_solutions_reach_full_agreement(upload_gen_input: _GenInputUploader) -> None:
    inputs = [
        DiffInputRef(ordinal=1, input_s3_key=upload_gen_input(b"2 3\n")),
        DiffInputRef(ordinal=2, input_s3_key=upload_gen_input(b"10 20\n")),
    ]
    result = run_diff(_job(reference=CORRECT_PY, brute_force=CORRECT_PY, inputs=inputs))
    assert result.status == DiffStatus.COMPLETED
    assert result.agreement_pct == 1.0
    assert all(case.agree for case in result.cases)


def test_capture_agreement_outputs_populates_reference_output_on_agreement(
    upload_gen_input: _GenInputUploader,
) -> None:
    # Slice 3's test-case factory needs the reference's output even when the
    # two solutions agree — that becomes a kept test case's expected output.
    inputs = [DiffInputRef(ordinal=1, input_s3_key=upload_gen_input(b"2 3\n"))]
    result = run_diff(
        _job(
            reference=CORRECT_PY,
            brute_force=CORRECT_PY,
            inputs=inputs,
            capture_agreement_outputs=True,
        )
    )
    assert result.agreement_pct == 1.0
    case = result.cases[0]
    assert case.agree
    assert case.reference_output_b64 is not None
    # Brute-force output is only ever needed for the discard log —
    # never captured on agreement, flag or no flag.
    assert case.brute_force_output_b64 is None


def test_capture_agreement_outputs_defaults_to_off(
    upload_gen_input: _GenInputUploader,
) -> None:
    inputs = [DiffInputRef(ordinal=1, input_s3_key=upload_gen_input(b"2 3\n"))]
    result = run_diff(_job(reference=CORRECT_PY, brute_force=CORRECT_PY, inputs=inputs))
    assert result.cases[0].agree
    assert result.cases[0].reference_output_b64 is None


def test_disagreeing_solutions_are_flagged_with_both_outputs(
    upload_gen_input: _GenInputUploader,
) -> None:
    inputs = [DiffInputRef(ordinal=1, input_s3_key=upload_gen_input(b"2 3\n"))]
    result = run_diff(_job(reference=CORRECT_PY, brute_force=WRONG_PY, inputs=inputs))
    assert result.status == DiffStatus.COMPLETED
    assert result.agreement_pct == 0.0
    case = result.cases[0]
    assert not case.agree
    assert case.reference_output_b64 is not None
    assert case.brute_force_output_b64 is not None


def test_reference_compile_error(upload_gen_input: _GenInputUploader) -> None:
    inputs = [DiffInputRef(ordinal=1, input_s3_key=upload_gen_input(b"2 3\n"))]
    result = run_diff(_job(reference=INVALID_PY, brute_force=CORRECT_PY, inputs=inputs))
    assert result.status == DiffStatus.REFERENCE_COMPILE_ERROR
    assert result.cases == []
    assert result.compile_error


def test_brute_force_compile_error(upload_gen_input: _GenInputUploader) -> None:
    inputs = [DiffInputRef(ordinal=1, input_s3_key=upload_gen_input(b"2 3\n"))]
    result = run_diff(_job(reference=CORRECT_PY, brute_force=INVALID_PY, inputs=inputs))
    assert result.status == DiffStatus.BRUTE_FORCE_COMPILE_ERROR
    assert result.cases == []
    assert result.compile_error
