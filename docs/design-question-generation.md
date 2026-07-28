# Design note: AI question generator + validation loop (Phase 2, Slice 2)

## Input / output

```
Input:  {topic_id, difficulty_band (easy|medium|hard), language_targets[]}
Output: a new, unpublished question version in the question service,
        created only after its reference and brute-force solutions agree
        on >= 95% of 100 generated inputs
Validation: differential testing via a new judge-gen SQS lane
Max attempts: 3 solution/validation attempts before the job is failed
              (the problem statement itself is generated once, not retried
              — see "What gets retried" below)
```

## Why this needs a real judge integration

Differential testing means running two LLM-generated, untrusted programs
and comparing their outputs. Per Hard Rule 5, untrusted code only ever
runs inside the existing sandboxed judge containers — never inline in
the `ai` service process. So this slice necessarily touches
`services/judge`, confirmed explicitly with the user before designing
further. The existing sandbox contract (`services/judge/app/sandbox.py`
— network-none, read-only rootfs, non-root user, resource limits) is
**not modified in any way**; this slice only adds a second, independent
consumption path that reuses it exactly as-is.

## New SQS lane: `judge-gen`

Two queues, mirroring the existing `dsa-submissions`/`dsa-verdicts`
naming: `dsa-judge-gen` (jobs, published by `ai`) and
`dsa-judge-gen-results` (results, published by judge, consumed by `ai`).
Existing `dsa-submissions`/`dsa-verdicts` (the "judge-live" lane) are
**untouched** — different queues, different worker process, so there is
no way for generation load to compete with candidate-submission latency.
Both queues are created lazily/idempotently on first use in dev
(matching how `dsa-submissions`/`dsa-verdicts` already work — no
localstack bootstrap script exists today). Terraform/`deploy.yml` wiring
for these queues is deferred, same scope call as Slice 1's readiness
items — this slice only needs to work in local dev + CI.

## New judge worker process (additive only)

- `services/judge/app/gen_contracts.py` — new Pydantic wire contracts,
  independent copies kept in sync by field name with `ai`'s copies (same
  no-cross-import convention as `SubmissionJob`/`VerdictMessage`):
  ```python
  class DiffInputRef(BaseModel):
      ordinal: int
      input_s3_key: str  # lives in ai's bucket, not question's

  class DiffJob(BaseModel):
      job_id: uuid.UUID
      org_id: uuid.UUID
      attempt: int
      language: Language          # reused enum
      reference_source: str
      brute_force_source: str
      limits: Limits               # reused
      compare_mode: CompareMode    # reused
      inputs: list[DiffInputRef]
      request_id: str | None = None

  class DiffCaseResult(BaseModel):
      ordinal: int
      agree: bool
      reference_verdict: Verdict   # AC used loosely here to mean "ran cleanly"
      brute_force_verdict: Verdict
      reference_output_b64: str | None = None   # populated only on disagreement,
      brute_force_output_b64: str | None = None # truncated — feeds the discard log

  class DiffStatus(enum.StrEnum):
      COMPLETED = "completed"
      REFERENCE_COMPILE_ERROR = "reference_compile_error"
      BRUTE_FORCE_COMPILE_ERROR = "brute_force_compile_error"

  class DiffResult(BaseModel):
      job_id: uuid.UUID
      org_id: uuid.UUID
      attempt: int
      status: DiffStatus
      agreement_pct: float
      cases: list[DiffCaseResult]
      request_id: str | None = None
  ```
- `services/judge/app/gen_runner.py` — `run_diff(job: DiffJob) -> DiffResult`:
  compile reference (fail fast → `REFERENCE_COMPILE_ERROR`, 0 runs wasted),
  compile brute force (fail fast → `BRUTE_FORCE_COMPILE_ERROR`), then for
  each input: run both compiled artifacts against it, `compare.outputs_match`
  the two outputs to each other (this function is already symmetric —
  confirmed reusable with zero changes). An input "agrees" only if both
  runs exit cleanly (not TLE/MLE/RE/truncated) **and** outputs match;
  anything else counts as a disagreement, with both sides' output
  captured (base64, truncated) for the discard log. Container invocation
  itself (`_run_container`, `SandboxSpec`, `build_run_command`, `_image`,
  `SOURCE_FILENAME`) is **extracted from `runner.py` into a shared
  `services/judge/app/exec_common.py`** so this new path reuses the exact
  hardened invocation rather than duplicating it — `runner.py`'s own
  behavior for judge-live submissions is unchanged, and `sandbox.py`
  itself is not touched at all.
- `services/judge/app/gen_worker.py` — new entrypoint, structurally a
  copy of `worker.py`'s poll/process/delete loop but pointed at
  `dsa-judge-gen` → `dsa-judge-gen-results`. Existing `worker.py` is not
  modified. Run as a **separate process** (`python -m app.gen_worker`),
  which is what makes `judge-gen` naturally lower-priority than
  `judge-live` — it's a completely independent consumer, so heavy
  generation traffic can never delay a candidate's real submission.
- `services/judge/app/config.py` gains `ai_s3_bucket: str = "ai-artifacts"`
  and `gen_jobs_queue`/`gen_results_queue` settings; `app/s3.py::get_object`
  gains an optional `bucket` parameter (default: existing `s3_bucket`, so
  judge-live is byte-for-byte unaffected) so `gen_runner.py` can read
  generated inputs from `ai`'s bucket instead of question's.
- `infra/docker-compose.yml`: new `judge-gen` service, same image as
  `judge`, `command: uv run python -m app.gen_worker`, same DooD
  mount/macOS caveat already documented for `judge`.

## `services/ai` generation pipeline

### Constraint-aware random input generation (not the LLM)

The prompt requires inputs to come from "a constraint-aware random input
generator, not LLM." Freeform constraint prose (`constraints_md`) isn't
machine-parseable, so the first LLM call also produces a small structured
**input spec** alongside the human-readable statement/constraints:
```python
class InputVar(BaseModel):
    name: str
    kind: Literal["int", "int_array", "string"]
    min_value: int | None = None
    max_value: int | None = None
    length_min: int | None = None   # for int_array/string
    length_max: int | None = None

class GeneratedQuestionDraft(BaseModel):
    title: str
    statement_md: str
    constraints_md: str
    examples: list[dict[str, str]]   # [{"input": ..., "output": ...}]
    starter_code: dict[str, str]     # per language_target
    input_spec: list[InputVar]
    difficulty: int                  # 1-5, validated against the requested band
```
`app/generation/input_generator.py::generate_inputs(spec, count=100) ->
list[str]` is a deterministic (seeded) Python function — no LLM call —
that fills each `InputVar` with a random value in range and renders them
in declared order, one line per var (space-separated for arrays), the
same format `app/pdf` and the judge runners already expect (stdin text).

### Static validation (before spending any judge compute)

`app/generation/validate.py::validate_draft(draft)`  checks: every
`InputVar`'s `min<=max` / `length_min<=length_max`; `difficulty` falls
inside the requested band's numeric range (`{"easy": (1,2), "medium":
(2,3), "hard": (4,5)}`); each declared `example` actually parses against
`input_spec` (catches "examples match declared I/O format"); starter
code present for every requested `language_target`. Any failure fails
the job immediately with no LLM solution calls and no judge submission —
this is what the "test static validation rejects bad constraints" test
requirement is exercising.

### What gets retried

The problem statement/spec (`GeneratedQuestionDraft`) is generated **once**
and does not change across attempts — regenerating the whole problem on
every retry would mean 3 attempts validate 3 different problems, not one
problem validated 3 ways. Only the **reference solution, brute-force
solution, and the random inputs** are regenerated each attempt (a
disagreement could come from either solution being wrong or from
unlucky/degenerate inputs, so regenerating all three together is the
simplest thing that can't get stuck retrying the same bad input set).

### `generation_job` table (ai service)

```
id                 uuid7 pk
org_id             uuid, indexed
topic_id           uuid            -- question service's id; no FK (cross-service)
difficulty_band    str
language_targets   text[]
status             queued | drafting | validating | succeeded | failed
attempt            int, default 0  -- 1..3 while validating
draft              jsonb           -- the GeneratedQuestionDraft, set once
reference_solution text, nullable  -- current attempt's; kept from the
brute_force_solution text, nullable -- winning attempt once succeeded
question_version_id uuid, nullable -- question service's id, once succeeded
discard_log        jsonb, nullable -- disagreeing cases from the final failed attempt
error              text, nullable
created_at / updated_at
```

### Flow

1. `POST /questions/generate` — creates the row (`status=queued`), fires
   an `asyncio.create_task` (same fire-and-forget shape as Slice 1's
   ingestion — still no queue needed on the *ai→judge submission* side
   for the *drafting* step; the queue exists for the judge round-trip).
2. Background task: LLM call → `GeneratedQuestionDraft` → `validate_draft`
   (fail fast on rejection) → store `draft`, `status=drafting`, then
   enter the attempt loop (`status=validating`, `attempt=1`):
   generate reference solution (LLM), brute-force solution (LLM,
   different prompt/temperature for independence), `generate_inputs`,
   upload each input to S3 (`ai-artifacts`, key
   `generation/{job_id}/{attempt}/input-{ordinal}.txt`), publish one
   `DiffJob` to `dsa-judge-gen`. The task returns here — the rest is
   driven by the results consumer.
3. A persistent background consumer (`app/services/gen_consumer.py`,
   started in `app/main.py`'s lifespan exactly like exam's verdict
   consumer, feature-flagged `enable_gen_result_consumer`) polls
   `dsa-judge-gen-results`. On a `DiffResult`: look up the job by
   `job_id`; if `agreement_pct >= 0.95` → `POST /questions` to the
   question service with the draft's content, store
   `question_version_id`, `status=succeeded`. If `< 0.95` and
   `attempt < 3` → bump `attempt`, regenerate solutions+inputs, publish
   another `DiffJob`. If `< 0.95` and `attempt == 3` → `status=failed`,
   store `discard_log` (the disagreeing cases from the final attempt,
   each side's truncated output).
4. `GET /questions/generate/{job_id}` — status + `question_version_id`
   when `succeeded`.
5. The created question stays in the question service's existing
   `draft` status — Slice 2 only proves the *solutions* agree with each
   other; it doesn't attach real hidden test cases (that's Slice 3) or
   publish the question. An examiner (or Slice 3) still has to approve
   it before it can appear in an exam, per `docs/architecture.md`.
6. `reference_solution`/`brute_force_solution` are kept on `ai`'s own
   `generation_job` row (keyed by `question_version_id` once succeeded)
   rather than invented as new storage in the question service — Slice
   3's factory prompt says it needs "question_version_id (with
   reference + brute-force solutions)" as input, and since `ai` is what
   generated them, `ai` remains their owner (no cross-service DB access;
   Slice 3 will call back into `ai`'s own API for them).

### LLM calls (all through the existing `LLMClient` abstraction)

Three calls, extending `app/llm/client.py`'s protocol with two new
methods (`draft_question`, `generate_solution`) alongside the existing
`extract_profile` — same mock-by-default backend as Slice 1, so this
slice needs no real Anthropic key either. `MockLLMClient` returns a
small fixed, internally-consistent draft (e.g. "sum of two numbers"
shape) and trivially-correct reference/brute-force solutions in Python,
so the full pipeline — including a real judge-gen round trip — is
exercised in tests without any network call.

### Tests

- `app/generation/input_generator.py`, `validate.py`: pure unit tests
  (seeded determinism, bound violations, malformed examples rejected).
- `services/ai/tests`: mock `LLMClient`; a fake `QueuePublisher` (mirrors
  exam's `get_publisher()` override pattern) capturing published
  `DiffJob`s instead of hitting real SQS, **plus** a real end-to-end
  variant using real localstack SQS + the real `judge-gen` worker
  process (mirrors `scripts/e2e.py`'s judge-worker dependency) to prove
  the full loop once, matching how Slice 1 verified via the live stack
  rather than only mocks.
- `services/judge/tests`: new tests for `gen_runner.run_diff` — agreement
  path, disagreement path (WA-equivalent), reference compile error,
  brute-force compile error — same fixture-runner-image pattern already
  used for `runner.run`.
- Retry logic: attempt 1 and 2 disagree, attempt 3 agrees → succeeds
  with `attempt=3`. All 3 disagree → `status=failed`, `discard_log`
  populated, no question created.
- 95% threshold: exactly 95/100 agreeing → succeeds; 94/100 → retries.

## Non-goals for this slice

Test-case factory (Slice 3), Mode 2 scheduling (Slice 4), adaptive
difficulty (Slice 5), live proctoring (Slice 6), evaluation (Slice 7),
hiring reports (Slice 8) are out of scope. Terraform/`deploy.yml` wiring
for the new queues and any `services/ai` ECS deployment follows the same
"local dev + CI only" scope call made in Slice 1.
