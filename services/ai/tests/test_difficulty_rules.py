from app.difficulty.rules import (
    MAX_DIFFICULTY,
    MIN_DIFFICULTY,
    band_for_difficulty,
    compute_next_difficulty,
)


def test_ac_fast_optimal_raises_by_one() -> None:
    next_value = compute_next_difficulty(
        3.0, verdict="AC", time_elapsed_pct=0.1, complexity_hint="optimal"
    )
    assert next_value == 4.0


def test_ac_fast_suboptimal_raises_by_half() -> None:
    next_value = compute_next_difficulty(
        3.0, verdict="AC", time_elapsed_pct=0.1, complexity_hint="suboptimal"
    )
    assert next_value == 3.5


def test_ac_fast_with_no_complexity_hint_is_conservative() -> None:
    next_value = compute_next_difficulty(
        3.0, verdict="AC", time_elapsed_pct=0.29, complexity_hint=None
    )
    assert next_value == 3.5


def test_ac_not_fast_holds() -> None:
    next_value = compute_next_difficulty(
        3.0, verdict="AC", time_elapsed_pct=0.5, complexity_hint="optimal"
    )
    assert next_value == 3.0


def test_failed_attempt_under_80_percent_holds() -> None:
    next_value = compute_next_difficulty(
        3.0, verdict="WA", time_elapsed_pct=0.79, complexity_hint=None
    )
    assert next_value == 3.0


def test_failed_attempt_past_80_percent_lowers_by_one() -> None:
    next_value = compute_next_difficulty(
        3.0, verdict="TLE", time_elapsed_pct=0.8, complexity_hint=None
    )
    assert next_value == 2.0


def test_difficulty_never_exceeds_max() -> None:
    next_value = compute_next_difficulty(
        MAX_DIFFICULTY, verdict="AC", time_elapsed_pct=0.0, complexity_hint="optimal"
    )
    assert next_value == MAX_DIFFICULTY


def test_difficulty_never_drops_below_min() -> None:
    next_value = compute_next_difficulty(
        MIN_DIFFICULTY, verdict="WA", time_elapsed_pct=1.0, complexity_hint=None
    )
    assert next_value == MIN_DIFFICULTY


def test_band_cutoffs() -> None:
    assert band_for_difficulty(1.0) == "easy"
    assert band_for_difficulty(2.0) == "easy"
    assert band_for_difficulty(2.5) == "medium"
    assert band_for_difficulty(3.0) == "medium"
    assert band_for_difficulty(3.5) == "hard"
    assert band_for_difficulty(5.0) == "hard"
