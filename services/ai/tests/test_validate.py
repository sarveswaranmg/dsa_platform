from app.generation.schemas import GeneratedExample, GeneratedQuestionDraft, InputVar
from app.generation.validate import validate_draft, validate_input


def _draft(**overrides: object) -> GeneratedQuestionDraft:
    defaults: dict[str, object] = dict(
        title="Add Two Numbers",
        statement_md="Read a and b; print a + b.",
        constraints_md="1 <= a, b <= 1000",
        examples=[GeneratedExample(input="2\n3", output="5")],
        starter_code={"python": "# solve\n"},
        input_spec=[
            InputVar(name="a", kind="int", min_value=1, max_value=1000),
            InputVar(name="b", kind="int", min_value=1, max_value=1000),
        ],
        difficulty=2,
    )
    defaults.update(overrides)
    return GeneratedQuestionDraft.model_validate(defaults)


def test_valid_draft_has_no_errors() -> None:
    assert validate_draft(_draft(), "easy", ["python"]) == []


def test_difficulty_outside_band_is_rejected() -> None:
    errors = validate_draft(_draft(difficulty=5), "easy", ["python"])
    assert any("difficulty" in e for e in errors)


def test_bad_bounds_rejected() -> None:
    draft = _draft(
        input_spec=[InputVar(name="a", kind="int", min_value=100, max_value=1)]
    )
    errors = validate_draft(draft, "easy", ["python"])
    assert any("min_value > max_value" in e for e in errors)


def test_missing_starter_code_for_requested_language_rejected() -> None:
    errors = validate_draft(_draft(), "easy", ["python", "java"])
    assert any("java" in e for e in errors)


def test_no_examples_rejected() -> None:
    errors = validate_draft(_draft(examples=[]), "easy", ["python"])
    assert any("no examples" in e for e in errors)


def test_example_with_wrong_line_count_rejected() -> None:
    draft = _draft(examples=[GeneratedExample(input="2", output="5")])
    errors = validate_draft(draft, "easy", ["python"])
    assert any("expected 2 input lines" in e for e in errors)


def test_example_value_out_of_bounds_rejected() -> None:
    errors = validate_draft(
        _draft(examples=[GeneratedExample(input="2\n99999", output="x")]), "easy", ["python"]
    )
    assert any("max_value" in e for e in errors)


def test_example_non_numeric_rejected() -> None:
    errors = validate_draft(
        _draft(examples=[GeneratedExample(input="2\nabc", output="x")]), "easy", ["python"]
    )
    assert any("not an int" in e for e in errors)


# validate_input — the same per-line/per-var checking `validate_draft` uses
# for worked examples, exposed publicly for the test-case factory (Phase 2
# Slice 3) to validate LLM-generated candidate inputs before ever
# submitting them to judge.

_SPEC = [
    InputVar(name="a", kind="int", min_value=1, max_value=1000),
    InputVar(name="b", kind="int", min_value=1, max_value=1000),
]


def test_validate_input_accepts_a_valid_candidate() -> None:
    assert validate_input("2\n3", _SPEC) == []


def test_validate_input_rejects_wrong_line_count() -> None:
    errors = validate_input("2", _SPEC)
    assert any("expected 2 input lines" in e for e in errors)


def test_validate_input_rejects_out_of_bounds_value() -> None:
    errors = validate_input("2\n99999", _SPEC)
    assert any("max_value" in e for e in errors)


def test_validate_input_rejects_non_numeric_token() -> None:
    errors = validate_input("2\nabc", _SPEC)
    assert any("not an int" in e for e in errors)


def test_validate_input_checks_int_array_bounds() -> None:
    spec = [
        InputVar(name="arr", kind="int_array", min_value=0, max_value=9, length_min=2, length_max=4)
    ]
    assert validate_input("1 2 3", spec) == []
    assert any("length" in e for e in validate_input("1", spec))
    assert any("max_value" in e for e in validate_input("1 2 99", spec))
