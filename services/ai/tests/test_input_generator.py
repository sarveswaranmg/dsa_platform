from app.generation.input_generator import generate_inputs
from app.generation.schemas import InputVar


def test_deterministic_with_same_seed() -> None:
    spec = [InputVar(name="n", kind="int", min_value=1, max_value=100)]
    first = generate_inputs(spec, count=10, seed=42)
    second = generate_inputs(spec, count=10, seed=42)
    assert first == second


def test_different_seeds_differ() -> None:
    spec = [InputVar(name="n", kind="int", min_value=1, max_value=1_000_000)]
    first = generate_inputs(spec, count=5, seed=1)
    second = generate_inputs(spec, count=5, seed=2)
    assert first != second


def test_respects_bounds() -> None:
    spec = [InputVar(name="n", kind="int", min_value=5, max_value=5)]
    for line in generate_inputs(spec, count=20, seed=7):
        assert line == "5"


def test_int_array_respects_length_and_value_bounds() -> None:
    spec = [
        InputVar(name="arr", kind="int_array", min_value=0, max_value=9, length_min=3, length_max=3)
    ]
    for line in generate_inputs(spec, count=20, seed=1):
        tokens = line.split()
        assert len(tokens) == 3
        assert all(0 <= int(t) <= 9 for t in tokens)


def test_multi_variable_spec_renders_one_line_each() -> None:
    spec = [
        InputVar(name="n", kind="int", min_value=1, max_value=5),
        InputVar(name="s", kind="string", length_min=2, length_max=2, charset="ab"),
    ]
    for blob in generate_inputs(spec, count=10, seed=3):
        lines = blob.split("\n")
        assert len(lines) == 2
        assert 1 <= int(lines[0]) <= 5
        assert len(lines[1]) == 2
        assert set(lines[1]) <= {"a", "b"}
