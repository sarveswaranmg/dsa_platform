from datetime import UTC, datetime, timedelta

from app.clients.exam_service import SubmissionRecord
from app.evaluation.behavioural import edge_cases_tested, failure_response, runs_before_ac

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _record(mode: str, verdict: str | None, offset_s: int) -> SubmissionRecord:
    return SubmissionRecord(
        mode=mode,
        language="python",
        source="print(1)",
        status="completed",
        summary_verdict=verdict,
        created_at=_START + timedelta(seconds=offset_s),
    )


def test_run_then_ac_counts_one_run_before_ac() -> None:
    records = [_record("run", None, 0), _record("submit", "AC", 1)]
    assert runs_before_ac(records) == 1
    assert edge_cases_tested(records) is True
    assert failure_response(records) is None


def test_straight_to_submit_ac_has_no_runs_or_prior_failure() -> None:
    records = [_record("submit", "AC", 0)]
    assert runs_before_ac(records) == 0
    assert edge_cases_tested(records) is False
    assert failure_response(records) is None


def test_wa_then_immediate_resubmit() -> None:
    records = [_record("submit", "WA", 0), _record("submit", "AC", 1)]
    assert runs_before_ac(records) == 0
    assert edge_cases_tested(records) is False
    assert failure_response(records) == "resubmitted_immediately"


def test_wa_then_run_then_resubmit() -> None:
    records = [
        _record("submit", "WA", 0),
        _record("run", None, 1),
        _record("submit", "AC", 2),
    ]
    assert runs_before_ac(records) == 1
    assert edge_cases_tested(records) is True
    assert failure_response(records) == "ran_before_resubmitting"


def test_wa_then_give_up() -> None:
    records = [_record("submit", "WA", 0)]
    assert runs_before_ac(records) == 0
    assert failure_response(records) == "no_further_attempt"
