import uuid
from typing import Literal

from pydantic import BaseModel, Field

# Numeric difficulty range (question service's 1-5 scale) each band maps to.
DIFFICULTY_BANDS: dict[str, tuple[int, int]] = {
    "easy": (1, 2),
    "medium": (2, 3),
    "hard": (4, 5),
}


class InputVar(BaseModel):
    """One variable in a problem's input format — enough structure for a
    deterministic generator to fill it with a valid random value without
    having to parse freeform constraint prose. Rendered one per line, in
    declared order, matching the stdin format the judge runners expect."""

    name: str
    kind: Literal["int", "int_array", "string"]
    min_value: int | None = None
    max_value: int | None = None
    length_min: int | None = None  # for int_array / string
    length_max: int | None = None
    charset: str = "abcdefghijklmnopqrstuvwxyz"  # for string


class GeneratedExample(BaseModel):
    input: str
    output: str


class GeneratedQuestionDraft(BaseModel):
    """The LLM's structured output for one generation job. Generated once
    per job — retries only regenerate the solutions and inputs, never this
    draft (see docs/design-question-generation.md)."""

    title: str = Field(min_length=1, max_length=300)
    statement_md: str = Field(min_length=1)
    constraints_md: str = ""
    examples: list[GeneratedExample] = Field(default_factory=list)
    starter_code: dict[str, str] = Field(default_factory=dict)  # per language_target
    input_spec: list[InputVar]
    difficulty: int = Field(ge=1, le=5)


class GeneratedTestCase(BaseModel):
    """One LLM-drafted test-case candidate (Phase 2 Slice 3's test-case
    factory) — validated against the draft's `input_spec` before ever being
    submitted to judge for differential testing."""

    input: str
    description: str
    case_type: Literal["edge", "adversarial", "stress"]


class AvailableTopic(BaseModel):
    """One topic the requesting org has defined, passed in by `exam` (which
    already holds an examiner token to ask question service for the org's
    topic list — `ai` has no other way to know valid topic ids for that org)."""

    id: uuid.UUID
    name: str


class BlueprintSlot(BaseModel):
    """One topic slot in an LLM-proposed exam blueprint (Phase 2 Slice 4).
    The LLM only picks a difficulty band per slot — `difficulty_min`/`_max`
    are filled in server-side from `DIFFICULTY_BANDS`, never chosen directly,
    keeping this consistent with how question generation already reasons
    about difficulty."""

    topic_id: uuid.UUID
    weight: int = Field(ge=1, le=100)
    difficulty_band: Literal["easy", "medium", "hard"]
    difficulty_min: int = Field(ge=1, le=5)
    difficulty_max: int = Field(ge=1, le=5)
    question_count: int = Field(ge=1)


class BlueprintSpec(BaseModel):
    """The LLM's structured proposal for a Mode 2 exam's blueprint. `exam`
    converts `topic_mix` into its own `TopicMixEntry` shape unchanged —
    weights must sum to 100 and topic_ids must be unique, same constraints
    `exam`'s blueprint schema already enforces."""

    topic_mix: list[BlueprintSlot]
    total_duration_minutes: int = Field(ge=1, le=1440)
    rationale: str
