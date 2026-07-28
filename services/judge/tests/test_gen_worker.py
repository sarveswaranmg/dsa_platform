"""Unit tests for gen_worker's message routing — mocks `run_diff` entirely
(no Docker/localstack needed) since these only exercise which queue a
result gets published to, not real differential execution."""

import uuid

import pytest

from app import gen_worker, sqs
from app.config import get_settings
from app.contracts import CompareMode, Language, Limits
from app.gen_contracts import DiffJob, DiffResult, DiffStatus


def _job(*, results_queue: str | None = None) -> DiffJob:
    return DiffJob(
        job_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        attempt=1,
        language=Language.PYTHON,
        reference_source="print(1)\n",
        brute_force_source="print(1)\n",
        limits=Limits(time_ms=1000, memory_mb=64),
        compare_mode=CompareMode.WHITESPACE,
        inputs=[],
        results_queue=results_queue,
    )


def _canned_result(job: DiffJob) -> DiffResult:
    return DiffResult(
        job_id=job.job_id,
        org_id=job.org_id,
        attempt=job.attempt,
        status=DiffStatus.COMPLETED,
        agreement_pct=1.0,
        cases=[],
    )


def test_publishes_to_default_queue_when_no_results_queue_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job()
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(gen_worker, "run_diff", lambda j: _canned_result(j))
    monkeypatch.setattr(sqs, "send", lambda queue, body: sent.append((queue, body)))

    gen_worker.process_message(job.model_dump_json())

    assert len(sent) == 1
    queue, body = sent[0]
    assert queue == get_settings().gen_results_queue
    assert DiffResult.model_validate_json(body).job_id == job.job_id


def test_publishes_to_job_specified_results_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _job(results_queue="dsa-judge-gen-sync-abc123")
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(gen_worker, "run_diff", lambda j: _canned_result(j))
    monkeypatch.setattr(sqs, "send", lambda queue, body: sent.append((queue, body)))

    gen_worker.process_message(job.model_dump_json())

    assert len(sent) == 1
    queue, _body = sent[0]
    assert queue == "dsa-judge-gen-sync-abc123"


def test_drops_unparseable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(sqs, "send", lambda queue, body: sent.append((queue, body)))

    gen_worker.process_message("not valid json")

    assert sent == []
