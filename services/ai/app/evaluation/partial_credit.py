"""Deterministic partial-credit scoring (Phase 2 Slice 7, see
docs/design-ai-evaluation.md). `approach_correct`/`bug_severity` come from
the LLM's `evaluate_submission` assessment — this function only maps that
judgement onto a score, it never assesses anything itself.
"""

from typing import Literal

BugSeverity = Literal["none", "minor", "major", "fundamental"]


def score(
    verdict: str | None,
    *,
    has_submission: bool,
    approach_correct: bool,
    bug_severity: BugSeverity,
) -> float:
    if not has_submission:
        return 0.0
    if verdict == "AC":
        return 1.0
    if approach_correct and bug_severity == "minor":
        return 0.7
    if approach_correct and bug_severity == "major":
        return 0.4
    return 0.1  # fundamentally wrong approach
