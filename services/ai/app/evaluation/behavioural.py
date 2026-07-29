"""Behavioural signals (Phase 2 Slice 7, see docs/design-ai-evaluation.md) —
computed straight from one ordinal's submission history, no LLM involved.
`records` must already be sorted by `created_at` ascending.
"""

from typing import Literal

from app.clients.exam_service import SubmissionRecord

FailureResponse = Literal[
    "ran_before_resubmitting", "resubmitted_immediately", "no_further_attempt"
]


def runs_before_ac(records: list[SubmissionRecord]) -> int:
    count = 0
    for record in records:
        if record.mode == "run":
            count += 1
        elif record.mode == "submit" and record.summary_verdict == "AC":
            return count
    return count


def edge_cases_tested(records: list[SubmissionRecord]) -> bool:
    submit_indices = [i for i, r in enumerate(records) if r.mode == "submit"]
    final_submit = submit_indices[-1] if submit_indices else len(records)
    return any(r.mode == "run" for r in records[:final_submit])


def failure_response(records: list[SubmissionRecord]) -> FailureResponse | None:
    """`None` if there's no failed submit to react to. If the candidate's
    very last submit itself failed (nothing came after it),
    `"no_further_attempt"`. Otherwise, classifies how they responded to the
    submit immediately before their final (successful) one, if that prior
    submit had failed."""
    submits = [r for r in records if r.mode == "submit"]
    if not submits:
        return None
    if submits[-1].summary_verdict != "AC":
        return "no_further_attempt"
    if len(submits) < 2 or submits[-2].summary_verdict == "AC":
        return None

    previous_index = records.index(submits[-2])
    final_index = records.index(submits[-1])
    between = records[previous_index + 1 : final_index]
    if any(r.mode == "run" for r in between):
        return "ran_before_resubmitting"
    return "resubmitted_immediately"
