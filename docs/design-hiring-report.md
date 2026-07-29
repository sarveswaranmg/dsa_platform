# Design: Hiring signal report (Phase 2 Slice 8)

## Goal

Once a session's evaluation is complete (Slice 7's `evaluation-complete`
event), synthesize everything known about the candidate's performance
into a structured `HiringReport` (seniority match, strong/weak areas,
code quality, problem-solving narrative, overall score, recommendation,
per-question evidence) — architecture.md §4.4.6's exact JSON shape.
Stored in `services/ai`, pushed into exam so `GET /sessions/{id}/report`
(reviewer/admin only) is a single-row read, and an email notifies the
examiner/reviewer it's ready. This is the last Phase 2 slice.

## Two confirmed scope decisions (do not re-litigate)

1. **`Exam.candidate_profile_id`** (nullable, additive): `schedule_ai_exam`
   (`services/exam/app/services/ai_scheduling.py`) already receives
   `candidate_profile_id` as a parameter but discards it after calling
   ai — persist it on `Exam` going forward. Mode 1 (manual) exams stay
   `NULL`; the report generator treats a candidate profile as optional.
2. **Report storage: columns on `ExamSession`**, not a new exam-side
   table — `hiring_report_json` (JSONB), `hiring_report_recommendation`,
   `hiring_report_generated_at`. It's a 1:1-per-session singleton
   (unlike Slice 6's genuinely append-only `session_events`), mirroring
   Slice 5's `current_difficulty`/`current_difficulty_band` columns
   exactly.

## Evidence is deterministic, not LLM-authored

The `evidence` array (`{question, verdict, approach, complexity,
partial_score}` per question) is assembled by the service from data
that's already fully known — `session_evaluations` (ai's own DB, direct
repo read), the graded verdict per ordinal (re-using
`ExamServiceClient.list_session_questions`, same "last `mode=submit` is
canonical" rule Slice 7 established), and each question's title (re-using
`QuestionServiceClient.get_version_content`). None of this needs an LLM
and hallucination risk on structured facts is exactly what "cite specific
evidence for every claim" is guarding against.

**`LLMClient.synthesize_hiring_report`** therefore returns a *narrower*
schema — only the narrative/judgement fields (`seniority_match`,
`strong_areas`, `weak_areas`, `code_quality`, `problem_solving`,
`overall_score`, `recommendation`) — with the deterministic `evidence`
array passed in as prompt *input* the model must ground its narrative in.
The service merges the two into the final `HiringReport` before Pydantic-
validating and storing it. This keeps the LLM's JSON contract small
(easier to validate, easier to test against malformed output) and the
factual evidence table 100% reliable regardless of what the model does.
`strong_areas`/`weak_areas` are free-text topic labels the model infers
from each question's title/statement — no new question-service topic-
taxonomy plumbing needed (statements already flow into the prompt).

## New pieces

### `services/exam`

- `app/models/exam.py`: `candidate_profile_id: uuid.UUID | None` (nullable
  additive column).
- `app/services/ai_scheduling.py::schedule_ai_exam`: persist it when
  creating the `Exam` row (mirrors how `target_role`/`experience_band`
  already flow into the blueprint version it creates).
- `app/models/exam_session.py`: `hiring_report_json: dict | None` (JSONB),
  `hiring_report_recommendation: str | None`,
  `hiring_report_generated_at: datetime | None`.
- `app/api/routes/internal.py`: new `GET /internal/sessions/{id}` —
  returns `candidate_email`, `target_role`, `experience_band`,
  `candidate_profile_id` (joins `Exam` → `BlueprintVersion` via the
  session's `exam_id`/`blueprint_version_id`). This is exam's first
  internal route returning exam-level (not just session-question-level)
  context — Slice 7's `GET /internal/sessions/{id}/questions` only
  covers assigned questions + submissions.
- `app/api/routes/internal.py`: new `POST /internal/sessions/{id}/report`
  — body `{report_json, recommendation}`. Writes the three new
  `ExamSession` columns, then calls exam's own `EmailSender` (already
  DI'd, no HTTP) to send the report-ready email — mirrors
  `scheduling.py::send_invite`'s exact pattern. This is exam's first
  internal *write* route (Slice 7's was read-only); no reverse ai→exam
  push existed before this slice (Slice 5's difficulty engine is exam
  *pulling* from ai, not ai pushing into exam).
- `app/api/routes/results.py` (or a new route file): `GET
  /sessions/{id}/report` — `require_role(Role.REVIEWER, Role.ADMIN)`
  (direct precedent: `results.py`'s existing multi-role
  `require_role(Role.ADMIN, Role.REVIEWER, Role.PROCTOR)`). 404s if no
  report has been generated yet.

### `services/ai`

- `app/models/hiring_report.py`: new `HiringReport` table — `id, org_id,
  session_id (unique), report_json (JSONB), recommendation, score,
  created_at`. ai's own durable copy (the source of truth it POSTs from);
  exam's columns are a served-read cache.
- `app/repositories/hiring_reports.py`: `upsert` (idempotent, same
  `on_conflict_do_nothing` pattern as `session_evaluations`, keyed on
  `session_id`).
- `app/clients/exam_service.py`: extend `ExamServiceClient` with
  `get_session_context(*, org_id, session_id) -> SessionContext`
  (candidate_email, target_role, experience_band, candidate_profile_id)
  and `attach_hiring_report(*, org_id, session_id, report_json,
  recommendation) -> None`.
- `app/repositories/profiles.py`: reuse existing `get_by_id` — no new
  query needed, just called conditionally when `candidate_profile_id` is
  present.
- `app/llm/client.py`: new `HiringReportNarrative(BaseModel)` (the
  narrower schema above) + `synthesize_hiring_report(*, target_role,
  experience_band, profile, evidence) -> HiringReportNarrative` on the
  `LLMClient` Protocol + `MockLLMClient` (deterministic, derived from
  average partial_score) + `AnthropicLLMClient` (same `_call` +
  `model_validate_json` pattern as every other method).
- `app/messaging/eval_contracts.py`: already has `EvaluationCompleteEvent`
  from Slice 7 — reused as-is, no new contract needed for the trigger.
- New `app/services/hiring_report_consumer.py`, mirroring
  `session_evaluation_consumer.py`'s exact shape:
  `process_evaluation_complete(session, body, *, llm_client,
  question_client, exam_client)`:
  1. `session_evaluations_repo.list_by_session` (ai's own DB).
  2. `exam_client.list_session_questions` for verdicts (reuse, Slice 7).
  3. `exam_client.get_session_context` for candidate_email/target_role/
     experience_band/candidate_profile_id (new).
  4. If `candidate_profile_id` is set, `profiles_repo.get_by_id` (ai's
     own DB, optional).
  5. Build the `evidence` list (question titles via
     `question_client.get_version_content`, one call per evaluated
     ordinal — same pattern as Slice 7's evaluation consumer).
  6. `llm_client.synthesize_hiring_report(...)`.
  7. Assemble the final `HiringReport`, Pydantic-validate, `upsert` into
     ai's `hiring_report` table.
  8. `exam_client.attach_hiring_report(...)` — pushes it into exam
     (triggers the email there, per the design above).
  - `run_hiring_report_consumer` — identical long-poll/delete-on-success
    loop shape to `run_session_evaluation_consumer`, polling
    `evaluation_complete_queue`.
- `app/main.py`: wire the new consumer into `lifespan`, same
  gate-by-settings-flag pattern (`enable_hiring_report_consumer`).
- Migration: `make migrate SVC=ai MSG="hiring reports"`.

### `frontend`

- `frontend/src/api/examiner/types.ts` + `endpoints.ts`: `HiringReport`
  type + `getHiringReport(examId)` (`GET /sessions/{id}/report` — but
  routed by `exam_id` from the examiner's point of view, same as
  `ResultsPage.tsx`'s existing submissions fetch keys off `exam_id`; the
  route itself is session-keyed since 1 exam = 1 session in Phase 1/2,
  same assumption `ResultsPage.tsx` already makes).
- New `frontend/src/components/HiringReportPanel.{tsx,css,test.tsx}`,
  colocated per the existing `VerdictPanel`/`RequirementsChangedBanner`
  convention: seniority-match badge, strong/weak area tag lists, an
  overall-score bar, a recommendation chip (proceed/maybe/reject color-
  coded), and the evidence table (one row per question).
- `frontend/src/routes/examiner/ResultsPage.tsx`: render
  `HiringReportPanel` above the submissions table when a report exists
  (404 → not rendered, no error state — report generation is
  best-effort/async and may simply not have finished yet).

## Test plan

- exam: `candidate_profile_id` persisted by `schedule_ai_exam`;
  `GET /internal/sessions/{id}` returns the right shape, 404 for unknown
  session; `POST /internal/sessions/{id}/report` writes the three columns
  and sends an email (assert against exam's existing fake `EmailSender`
  test fixture); `GET /sessions/{id}/report` 404s pre-generation, returns
  the stored JSON post-generation, 403s for AUTHOR/PROCTOR roles.
- ai: `synthesize_hiring_report` mock-client determinism; schema
  validation rejects a malformed LLM response (missing field / wrong
  `recommendation` enum value) without ever reaching the repo; the
  consumer's happy path (2 evaluated questions → evidence list built
  correctly, report upserted, `attach_hiring_report` called with the
  right payload); a session with no `candidate_profile_id` still
  produces a report (profile section just omitted from the prompt);
  redelivery of the same `evaluation-complete` event is idempotent
  (upsert, no duplicate row, `attach_hiring_report` called again is
  harmless — exam's own write is already idempotent by construction,
  just overwriting the same three columns).
- frontend: `HiringReportPanel` renders all five visual elements from a
  fixture report; `ResultsPage` shows nothing extra when the report
  fetch 404s.

## Non-goals

- No UI for triggering report regeneration — it's purely event-driven
  off `evaluation-complete`.
- No pagination/history of multiple reports per session — one report per
  session, upserted in place if ever regenerated.
- Phase 3's full-text/analytics use of hiring reports across sessions is
  out of scope.
