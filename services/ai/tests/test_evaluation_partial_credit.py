from app.evaluation.partial_credit import score


def test_no_submission_scores_zero() -> None:
    assert score(None, has_submission=False, approach_correct=False, bug_severity="none") == 0.0


def test_ac_scores_full_credit() -> None:
    assert score("AC", has_submission=True, approach_correct=True, bug_severity="none") == 1.0


def test_correct_approach_minor_bug_scores_0_7() -> None:
    assert score("WA", has_submission=True, approach_correct=True, bug_severity="minor") == 0.7


def test_correct_approach_major_bug_scores_0_4() -> None:
    assert score("WA", has_submission=True, approach_correct=True, bug_severity="major") == 0.4


def test_fundamentally_wrong_approach_scores_0_1() -> None:
    assert (
        score("WA", has_submission=True, approach_correct=False, bug_severity="fundamental")
        == 0.1
    )


def test_incorrect_approach_with_any_bug_severity_scores_0_1() -> None:
    # approach_correct=False always falls through to the "fundamentally
    # wrong" floor, regardless of what bug_severity says.
    assert score("TLE", has_submission=True, approach_correct=False, bug_severity="minor") == 0.1
