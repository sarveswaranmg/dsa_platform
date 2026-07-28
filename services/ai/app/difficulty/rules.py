"""Static rule engine (Phase 2 Slice 5, simplified IRT — see
docs/design-adaptive-difficulty.md). Calibration from real session data is
deferred to Phase 3; these rules are deliberately simple and hand-tuned.
"""

from typing import Literal

DEFAULT_DIFFICULTY = 3.0
MIN_DIFFICULTY = 1.0
MAX_DIFFICULTY = 5.0

ComplexityHint = Literal["optimal", "suboptimal"]


def compute_next_difficulty(
    current: float,
    *,
    verdict: str,
    time_elapsed_pct: float,
    complexity_hint: ComplexityHint | None,
) -> float:
    """`verdict` is judge's summary string (AC/WA/TLE/MLE/RE/CE) — anything
    other than "AC" is treated as a failed attempt. The two "raise" rules
    and the two "no raise" rules collapse to one branch each: AC only ever
    raises (if fast) or holds; a failed attempt only ever lowers (if very
    slow) or holds."""
    if verdict == "AC":
        delta = (1.0 if complexity_hint == "optimal" else 0.5) if time_elapsed_pct < 0.30 else 0.0
    else:
        delta = -1.0 if time_elapsed_pct >= 0.80 else 0.0
    return min(MAX_DIFFICULTY, max(MIN_DIFFICULTY, current + delta))


def band_for_difficulty(value: float) -> str:
    # A standalone cutoff scheme for this continuous 1.0-5.0 scale — not a
    # reuse of generation/schemas.py's DIFFICULTY_BANDS, which is only ever
    # a per-band (lo, hi) validation range during question generation and
    # isn't a clean partition (gap between medium's 3 and hard's 4).
    if value <= 2.0:
        return "easy"
    if value <= 3.0:
        return "medium"
    return "hard"
