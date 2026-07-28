# Design note: AI test-case factory (Phase 2, Slice 3)

## Input / output

```
Input:  question_version_id — must belong to a *succeeded* Slice 2
        generation job (this slice does not support manually-authored
        questions; confirmed with the user — see "Scope" below)
Output: validated test cases attached to that question version in the
        question service (S3 + metadata), via a new internal endpoint
Case types: edge, adversarial, stress (10 each by default)
Validation: the same differential-testing machinery Slice 2 already
        built (DiffJob/DiffResult, judge-gen lane) — reused, not rebuilt
```

## Scope: AI-generated questions only

The factory needs three things for a question_version_id: a reference
solution, an independently-generated brute-force solution, and a
structured `input_spec` (bounds per input variable) to validate candidate
inputs against. Today only Slice 2's `ai.generation_jobs` table has all
three — manually-authored (Phase 1) questions have none of them (just
freeform `constraints_md` markdown, confirmed absent of any structured
spec anywhere in `services/question`). Per an explicit decision with the
user, this slice only supports question versions that trace back to a
**succeeded** `generation_jobs` row: `POST /test-cases/generate` looks
one up by `question_version_id`; if none exists, the request is rejected
immediately. Extending to examiner-supplied reference solutions for
manually-authored questions (per `docs/architecture.md`'s "reference
solution the proctor supplies or approves") is left for a later slice.

## Reusing Slice 2's judge-gen lane as-is

Submitting the 30 (or 10, on-demand) candidate inputs against the
reference/brute-force pair is **exactly** Slice 2's differential-testing
job — same `DiffJob`/`DiffResult` contracts, same `gen_runner.run_diff`,
same queue. Two small, additive extensions to that machinery (both
inside code this project added in Slice 2, not `judge-live`/`sandbox.py`):

1. **`DiffJob.capture_agreement_outputs: bool = False`** (both judge's
   and ai's copies of the contract). Slice 2 only needed the reference's
   output on *disagreement* (for the discard log), so `gen_runner`
   only populated `reference_output_b64` then. Slice 3 needs the
   reference's output on *agreement* too (that becomes the test case's
   expected-output content) — but Slice 2's question-generation jobs run
   up to 100 inputs per attempt, and always capturing every output would
   risk the 256KB SQS message-size ceiling for that lane. The new flag
   defaults to `False` (Slice 2 callers untouched, unchanged behavior);
   Slice 3 sets it `True` on its (much smaller, 10-30 input) jobs, and
   `gen_runner` captures `reference_output_b64` whenever `agree` is true
   **or** disagreement (existing behavior), regardless of the flag.
2. **`DiffJob.results_queue: str | None = None`** + `gen_worker.py`
   publishing to `job.results_queue or settings.gen_results_queue`.
   Needed for the on-demand synchronous variant (below) so it doesn't
   contend with the persistent async consumer over the same queue.

## New internal endpoint on `services/question`

`POST /internal/question-versions/{question_id}/test-cases` (naming
matches the existing `question_id`-keyed examiner route, not
`version_id` — `ensure_mutable_version` resolves the current version
itself, exactly like the examiner-facing endpoint does) — body
`{org_id, is_sample: bool = False}`, no auth (same trusted-network
convention as `/internal/questions` added in Slice 2). Directly reuses
`test_cases_service.create_test_case(...)` — the *exact* function the
examiner-facing `POST /questions/{id}/test-cases` already calls — so
behavior (ordinal assignment, copy-on-write via `ensure_mutable_version`)
is identical, just callable without a bearer token. Returns the same
shape as the examiner endpoint: `{id, ordinal, upload_input_url,
upload_output_url}`. The ai factory job PUTs the generated input and the
reference's output straight to those URLs — same "presign then PUT"
pattern already used for candidate profile resumes (Slice 1) and
question test cases (Phase 1).

## `services/ai` — new `test_case_generation_job` table

A **separate** table from Slice 2's `generation_jobs`, not a reuse of its
`discard_log` column (the Phase 2 prompt doc's shorthand — "log
discarded cases to `generation_job.discard_log`" — predates this
scoping decision; overloading one row's terminal `succeeded` status
with a second, independent job lifecycle would conflate two different
concerns). Mirrors `generation_jobs`' shape:

```
id                    uuid7 pk
org_id                uuid, indexed
question_id           uuid            -- question service's id, no FK
question_version_id   uuid            -- the version cases attach to
generation_job_id     uuid            -- the Slice 2 job this reuses solutions from
synchronous           bool            -- on-demand variant (see below)
status                queued | generating | validating | succeeded | failed
kept_case_count       int, default 0
discard_log           jsonb, nullable -- disagreeing candidates
error                 text, nullable
created_at / updated_at
```

## Flow (async / default variant)

1. `POST /test-cases/generate {question_version_id}` — look up the
   succeeded `generation_jobs` row for that version (404 if none);
   create `test_case_generation_job` (`status=queued`), fire
   `asyncio.create_task` (same shape as Slice 1/2's background tasks).
2. Background task: `status=generating` → `LLMClient.generate_test_cases`
   (new method: given the draft, produce 10 edge + 10 adversarial + 10
   stress candidates, each `{input, description, case_type}`, strict
   JSON) → for each candidate, validate its `input` against the stored
   `input_spec` (reusing/extending `app/generation/validate.py`'s
   per-variable bound checking — extracted into a new public
   `validate_input(text, spec) -> str | None` so both example validation
   and candidate-input validation share it) — malformed candidates are
   dropped immediately, never submitted to judge.
3. Upload the valid candidates' inputs to S3 (`ai-artifacts`,
   `test-cases/{job.id}/input-{n}.txt`), publish one `DiffJob` (with
   `capture_agreement_outputs=True`) using the **generation job's**
   stored `reference_solution`/`brute_force_solution` — `status=validating`.
4. The **same** `gen_consumer` used by Slice 2 handles the result
   (`process_gen_result` gains a branch: if the message correlates to a
   `test_case_generation_job` instead of a `generation_jobs` row —
   distinguished by trying `test_case_generation_jobs` first, since
   `DiffJob.job_id` values are never reused between the two tables —
   route to the test-case finalizer instead of the question finalizer).
5. Finalizer: for each `DiffCaseResult` with `agree=True`, call the new
   `POST /internal/question-versions/{question_id}/test-cases`, PUT the
   candidate's input and the reference's output (decoded from
   `reference_output_b64`) to the returned presigned URLs.
   Disagreements go into `discard_log`. `status=succeeded` with
   `kept_case_count` set; a factory run with **zero** kept cases is
   still `succeeded` (with `kept_case_count=0`) rather than `failed` —
   there's no "retry" concept here (unlike Slice 2, a single differential
   pass is the whole job; failure is reserved for actual errors, e.g. the
   LLM call raising or the source generation job going missing).
6. `GET /test-cases/generate/{job_id}` — status + `kept_case_count`.

## On-demand (synchronous) variant

`POST /test-cases/generate?mode=sync` (or a distinct request field —
decided at implementation time in favor of whatever reads cleanest) runs
the same pipeline inline within the HTTP request instead of via
`asyncio.create_task`+consumer, for exactly 10 cases, hard-capped at 30
seconds total. To avoid contending with the persistent `gen_consumer`
over `dsa-judge-gen-results`, the synchronous path creates a throwaway,
uniquely-named results queue (`dsa-judge-gen-sync-{job_id}`, via the
already-idempotent `queue_url()` helper), sets `DiffJob.results_queue`
to it, and polls **that** queue directly with a deadline instead of
going through `gen_consumer` at all. On timeout, the job is marked
`failed` with a clear "judge did not respond within 30s" error — this is
the on-demand variant's main new test coverage requirement.

## Tests

- `app/generation/validate.py`: unit tests for the new
  `validate_input(text, spec)` extraction (bound violations, malformed
  tokens) — mirrors existing `test_validate.py` style.
- `services/ai`: mock `LLMClient.generate_test_cases`; fake
  `QueuePublisher`/question client (same fakes as Slice 2's
  `test_generation.py`) — happy path (some candidates rejected by the
  validator before ever reaching judge, some kept, some discarded by
  disagreement); a job with no matching succeeded `generation_jobs` row
  is rejected immediately; the on-demand variant's 30s timeout (using a
  fake/very short deadline in the test, not a real 30s wait).
- `services/question`: one test for the new internal test-case endpoint
  (mirrors the existing internal-endpoint test style; confirms
  copy-on-write still fires correctly if ever invoked against a
  published version, even though this slice's real callers only ever
  target draft versions).
- `services/judge`: extend `test_gen_runner.py` with a
  `capture_agreement_outputs=True` case asserting `reference_output_b64`
  is populated even when `agree=True`, and a `results_queue` case
  asserting `gen_worker.process_message` publishes to the job-specified
  queue instead of the default.

## Non-goals for this slice

Mode 2 scheduling (Slice 4), adaptive difficulty (Slice 5), live
proctoring (Slice 6 — though this slice's on-demand variant is exactly
what Slice 6 will call for mid-exam follow-ups), evaluation (Slice 7),
hiring reports (Slice 8). Manually-authored questions remain unsupported
by the factory, per the scope decision above. Terraform/`deploy.yml`
wiring stays out of scope, same as Slices 1-2.
