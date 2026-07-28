"""Constraint-aware random input generation — deterministic Python, never
the LLM (the LLM only produces the structured `input_spec` these bounds
come from; see docs/design-question-generation.md)."""

import random

from app.generation.schemas import InputVar


def _render_var(var: InputVar, rng: random.Random) -> str:
    if var.kind == "int":
        lo = var.min_value if var.min_value is not None else 0
        hi = var.max_value if var.max_value is not None else lo + 1000
        return str(rng.randint(lo, hi))

    if var.kind == "int_array":
        lo = var.min_value if var.min_value is not None else 0
        hi = var.max_value if var.max_value is not None else lo + 1000
        length_lo = var.length_min if var.length_min is not None else 1
        length_hi = var.length_max if var.length_max is not None else length_lo + 10
        length = rng.randint(length_lo, length_hi)
        return " ".join(str(rng.randint(lo, hi)) for _ in range(length))

    # string
    length_lo = var.length_min if var.length_min is not None else 1
    length_hi = var.length_max if var.length_max is not None else length_lo + 10
    length = rng.randint(length_lo, length_hi)
    charset = var.charset or "abcdefghijklmnopqrstuvwxyz"
    return "".join(rng.choice(charset) for _ in range(length))


def generate_inputs(spec: list[InputVar], count: int, seed: int | None = None) -> list[str]:
    """One stdin blob per generated case: each of `spec`'s variables rendered
    on its own line, in declared order — the same format the judge runners
    already read (see e.g. scripts/seed.py's seeded questions)."""
    rng = random.Random(seed)
    return ["\n".join(_render_var(var, rng) for var in spec) for _ in range(count)]
