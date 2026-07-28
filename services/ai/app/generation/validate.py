"""Static validation of a generated question draft — runs before any LLM
solution call or judge submission, so a malformed draft never wastes judge
compute. Returns a list of human-readable error strings; empty = valid."""

from app.generation.schemas import (
    DIFFICULTY_BANDS,
    GeneratedExample,
    GeneratedQuestionDraft,
    InputVar,
)


def _value_bounds_invalid(var: InputVar) -> bool:
    lo, hi = var.min_value, var.max_value
    return lo is not None and hi is not None and lo > hi


def _length_bounds_invalid(var: InputVar) -> bool:
    lo, hi = var.length_min, var.length_max
    return lo is not None and hi is not None and lo > hi


def _check_bounds(var: InputVar) -> str | None:
    if var.kind == "int":
        if _value_bounds_invalid(var):
            return f"{var.name}: min_value > max_value"
        return None
    if _length_bounds_invalid(var):
        return f"{var.name}: length_min > length_max"
    if var.kind == "int_array" and _value_bounds_invalid(var):
        return f"{var.name}: min_value > max_value"
    return None


def _check_value_against_var(line: str, var: InputVar) -> str | None:
    if var.kind == "int":
        try:
            value = int(line.strip())
        except ValueError:
            return f"{var.name}: {line!r} is not an int"
        if var.min_value is not None and value < var.min_value:
            return f"{var.name}: {value} < min_value {var.min_value}"
        if var.max_value is not None and value > var.max_value:
            return f"{var.name}: {value} > max_value {var.max_value}"
        return None

    if var.kind == "int_array":
        tokens = line.split()
        if var.length_min is not None and len(tokens) < var.length_min:
            return f"{var.name}: length {len(tokens)} < length_min {var.length_min}"
        if var.length_max is not None and len(tokens) > var.length_max:
            return f"{var.name}: length {len(tokens)} > length_max {var.length_max}"
        for token in tokens:
            try:
                value = int(token)
            except ValueError:
                return f"{var.name}: element {token!r} is not an int"
            if var.min_value is not None and value < var.min_value:
                return f"{var.name}: element {value} < min_value {var.min_value}"
            if var.max_value is not None and value > var.max_value:
                return f"{var.name}: element {value} > max_value {var.max_value}"
        return None

    # string
    if var.length_min is not None and len(line) < var.length_min:
        return f"{var.name}: length {len(line)} < length_min {var.length_min}"
    if var.length_max is not None and len(line) > var.length_max:
        return f"{var.name}: length {len(line)} > length_max {var.length_max}"
    return None


def validate_input(text: str, spec: list[InputVar]) -> list[str]:
    """Checks a raw stdin blob (one line per variable, in declared order)
    against `spec`'s bounds. Used both for a draft's worked `examples` and,
    in the test-case factory (Phase 2 Slice 3), for LLM-generated candidate
    test-case inputs before they're ever submitted to judge."""
    lines = text.split("\n")
    if len(lines) != len(spec):
        return [f"expected {len(spec)} input lines, got {len(lines)}"]
    errors = []
    for line, var in zip(lines, spec, strict=True):
        error = _check_value_against_var(line, var)
        if error:
            errors.append(error)
    return errors


def _validate_example(example: GeneratedExample, spec: list[InputVar]) -> list[str]:
    return validate_input(example.input, spec)


def validate_draft(
    draft: GeneratedQuestionDraft, difficulty_band: str, language_targets: list[str]
) -> list[str]:
    errors: list[str] = []

    band_lo, band_hi = DIFFICULTY_BANDS[difficulty_band]
    if not (band_lo <= draft.difficulty <= band_hi):
        errors.append(
            f"difficulty {draft.difficulty} outside {difficulty_band} band ({band_lo}-{band_hi})"
        )

    for var in draft.input_spec:
        error = _check_bounds(var)
        if error:
            errors.append(error)

    for language in language_targets:
        if not draft.starter_code.get(language):
            errors.append(f"missing starter code for {language}")

    if not draft.examples:
        errors.append("no examples provided")
    for index, example in enumerate(draft.examples):
        for error in _validate_example(example, draft.input_spec):
            errors.append(f"example {index}: {error}")

    return errors
