# Design: AI evaluation (Phase 2 Slice 7)

## Goal

Once a candidate's session ends, evaluate each submitted question beyond
the judge's binary AC/WA verdict: estimated time complexity, algorithm
approach, partial credit (0.0–1.0), and behavioural signals (run count
before AC, edge-case testing, response to failure). Runs async — never
blocks result delivery to the examiner. Stored in a new `session_evaluation`
table in `services/ai`, one row per (session, question). Feeds Slice 8's
hiring report (not built here — this slice only emits the
`evaluation-complete` event Slice 8 will subscribe to).

## Trigger: session-complete event

Today `services/exam` only detects "session over" lazily: `_lock_if_expired`
(`app/services/sessions.py:52-63`) flips `IN_PROGRESS → EXPIRED` the next
time anything touches the session (candidate or examiner request) after the
deadline passes. There is no scheduler and no "finish early" endpoint —
`SessionStatus.SUBMITTED` is defined but nothing ever sets it. This slice
does not add either of those; it hooks a publish into the one real
transition that exists: the moment `_lock_if_expired` sets `EXPIRED`, exam
publishes a lightweight `SessionCompleteEvent` (`org_id`, `session_id`,
`exam_id`) to a new `dsa-session-complete` queue, mirroring the
`submissions_queue`/`verdicts_queue` publish pattern in
`app/services/submissions.py:85`.

This means evaluation only starts once *something* re-touches an expired
session — acceptable for Phase 2 (an examiner opening results does this),
consistent with today's lazy-detection model, and out of scope to fix here.

## exam: exposing submission history

`Submission` (`app/models/submission.py`) has `session_id` and
`question_version_id` but no `ordinal` — after a Slice 6 follow-up changes
a session's assigned `question_version_id` mid-stream, old submissions
against the prior version and new ones against the forked version can't be
regrouped back to "the same question slot" by `question_version_id` alone.
Adding `ordinal: Mapped[int | None]` to `Submission` (additive migration,
populated by `submit()` in `app/services/sessions.py`, which already has
the ordinal in scope) fixes this — grouping submissions for evaluation by
`(session_id, ordinal)` stays correct across a follow-up.

New pieces:
- `app/repositories/submissions.py::list_by_session(session, *, org_id,
  session_id) -> list[Submission]`, ordered by `created_at` (mirrors the
  existing `list_by_exam`).
- New `app/api/routes/internal.py` (exam's first internal router — it has
  only ever been an internal *caller* before this slice): `GET
  /internal/sessions/{session_id}/submissions?org_id=...` returning each
  submission's `ordinal, question_version_id, mode, language, source,
  status, summary_verdict, created_at`. Unauthenticated, trusted-network
  only — already blocked at the gateway edge (`Route("/internal", None,
  Policy.BLOCKED)`), no gateway change needed.
- Also need question content (statement/constraints) for the LLM prompt —
  question service's existing `GET
  /internal/question-versions/{id}/content` (`InternalVersionContent`,
  already used by exam's own client) is reused as-is; `ai`'s
  `QuestionServiceClient` just gains a `get_version_content` method
  matching exam's client of the same name.

## ai: session-complete consumer

New `app/messaging/eval_contracts.py` (independent copy, no shared code
per the hard rule): `SessionCompleteEvent{org_id, session_id, exam_id}`,
`EvaluationCompleteEvent{org_id, session_id}`. New queue settings:
`session_complete_queue = "dsa-session-complete"`,
`evaluation_complete_queue = "dsa-evaluation-complete"`.

New `app/services/session_evaluation_consumer.py` mirrors
`app/services/gen_consumer.py` exactly (long-poll, delete-only-on-success,
blocking boto3 in a thread). `process_session_complete(session, body, *,
llm_client, question_client, exam_client, publisher)`:
1. Fetch the session's submission history via the new exam internal
   endpoint (`ExamServiceClient.list_session_submissions`).
2. Group by `ordinal`. For each ordinal with at least one `mode=submit`
   submission, take the **last** submit as the canonical graded attempt
   (matches "grading always references the latest state" already
   established for questions); ordinals with zero submits get a
   `partial_score=0.0`, no-submission row (no LLM call needed).
3. For a graded ordinal: fetch the question's statement/constraints (via
   `QuestionServiceClient.get_version_content`), run the complexity
   classifier over the submitted source, call
   `LLMClient.evaluate_submission(...)` for approach/bug assessment, run
   the deterministic partial-credit function, compute behavioural signals
   from the full (run + submit) history for that ordinal.
4. Upsert one `session_evaluation` row per ordinal (unique on
   `(session_id, ordinal)` — safe against SQS redelivery of the same
   session-complete event).
5. Once every assigned ordinal has a row, publish `evaluation-complete`.

**One LLM call per graded question**, not one bundled call for the whole
session — matches every existing `LLMClient` method (`draft_question`,
`generate_test_cases`, ...), each scoped to one artifact, keeping the
per-question JSON schema small and the failure blast radius (a bad/
malformed LLM response) limited to that one question's row instead of the
whole session.

## Complexity classifier (`app/evaluation/complexity.py`)

Pure functions, no LLM, unit-testable against known snippets:
- **Python**: `ast.parse`, walk the tree, compute the maximum nesting
  depth of `For`/`While` (a loop inside a loop increments depth; sibling
  loops don't). `depth 0` + a self-recursive call → `"O(2^n)"` (naive
  recursion heuristic); `depth 0` otherwise → `"O(1)"`; `depth 1` with a
  `sort(`/`sorted(` call present → `"O(n log n)"`; `depth 1` → `"O(n)"`;
  `depth 2` → `"O(n^2)"`; `depth >= 3` → `f"O(n^{depth})"`.
- **Java/C++**: no AST available — a basic heuristic scans for
  `for`/`while` keywords and tracks brace `{`/`}` depth, counting the
  maximum number of loop keywords seen at strictly increasing brace
  depths. Same depth→complexity mapping as Python, minus the recursion/
  sort refinements (source-text heuristics for those are too unreliable
  to bother with — "basic heuristics" per the slice prompt).

## Partial credit (`app/evaluation/partial_credit.py`)

Deterministic, mirrors the Slice 5 `difficulty/rules.py` style (a pure
function, table-tested):
```
score(verdict, has_submission, approach_correct, bug_severity) -> float
  no submission                      -> 0.0
  verdict == AC                      -> 1.0
  approach_correct, bug_severity=minor -> 0.7
  approach_correct, bug_severity=major -> 0.4
  otherwise (fundamentally wrong)     -> 0.1
```
`approach_correct`/`bug_severity` come from the LLM assessment
(`evaluate_submission`'s response), not invented by this function.

## Behavioural signals

Computed directly from the ordinal's full submission history (all modes,
timestamps, verdicts) — no LLM:
- `runs_before_ac`: count of `mode=run` submissions strictly before the
  first `mode=submit` with `summary_verdict=AC` (or before the last submit
  if never AC).
- `tested_edge_cases`: `True` if at least one `mode=run` submission exists
  before the final submit (candidate used the Run button at all).
- `failure_response`: for the submission immediately preceding the final
  graded one (if it failed), classify what happened next as
  `"ran_before_resubmitting" | "resubmitted_immediately" | "no_further_attempt"`.

## LLMClient.evaluate_submission (new protocol method)

```
async def evaluate_submission(
    self, *, statement_md: str, constraints_md: str, language: str,
    source: str, verdict: str,
) -> SubmissionAssessment: ...

class SubmissionAssessment(BaseModel):
    algorithm_family: str
    approach_correct: bool
    is_optimal: bool
    bug_description: str | None
    bug_severity: Literal["none", "minor", "major", "fundamental"]
```
Added to `LLMClient` Protocol, `MockLLMClient` (deterministic: `AC` →
correct/optimal/no bug; otherwise a fixed "off-by-one, minor" fixture),
and `AnthropicLLMClient` (same `_call` + `model_validate_json` pattern as
every other method).

## `session_evaluation` table (new model + migration, `services/ai`)

```
id                   uuid7 pk
org_id               uuid, indexed
session_id           uuid, indexed
ordinal              int
question_id          uuid
question_version_id  uuid
complexity           str | null   # "O(n^2)" etc.; null if no submission
approach             str | null   # algorithm_family; null if no submission
partial_score        float
behavioural_signals  jsonb        # {} if no submission
created_at / updated_at
```
Unique on `(session_id, ordinal)`.

## Test plan

- Complexity classifier: table-driven tests against known Python snippets
  (flat loop, nested double loop, sort-then-scan, naive recursion, no
  loop) and a couple of Java/C++ brace-nesting snippets.
- Partial credit: table-driven over all branches (AC, WA+minor,
  WA+major, fundamentally wrong, no submission).
- Behavioural signals: synthetic submission histories (run-then-AC,
  straight-to-submit-AC, WA-then-resubmit, WA-then-give-up).
- `process_session_complete`: mock LLM + exam/question clients — a full
  session with 2 questions (one AC, one with no submission) produces 2
  upserted rows and publishes `evaluation-complete`; redelivery of the
  same event doesn't duplicate rows (upsert idempotency).
- exam: `list_by_session` ordering; new internal endpoint returns the
  right shape and 404s for an unknown session; `Submission.ordinal`
  populated by `submit()`.
- Full stack verification deferred to the same "real end-to-end" pattern
  as prior slices where a live LLM/queue matters — here, since
  `LLM_BACKEND=mock` is deterministic and no WebSocket/browser is
  involved, plain `make test` coverage is sufficient; no separate manual
  e2e script needed for this slice.

## Non-goals

- Slice 8's `hiring_report`/report view — this slice only publishes
  `evaluation-complete`.
- Fixing lazy session-expiry detection (no scheduler/cron added).
- Rich static analysis for Java/C++ (brace-depth heuristic only, per the
  slice prompt's own wording).
