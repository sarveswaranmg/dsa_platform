# Design note: Mode 2 profile-driven exam scheduling (Phase 2, Slice 4)

## Input / output

```
Input:  candidate_profile_id (Slice 1) + target_role + seniority_band
        + candidate_email + starts_at/ends_at + language_targets
Output: a new exam, in a pending-review state, bound to specific
        AI-generated questions (not randomly sampled) — the examiner
        reviews/overrides before the invite is sent
Flow:   exam calls ai for a blueprint spec -> exam creates the blueprint
        -> exam fans out one Slice 2 generation job per slot (calling
        ai's *existing* endpoints directly) -> examiner reviews -> invite
```

## Two scope decisions confirmed with the user

1. **Overriding a slot regenerates it via AI** (a fresh Slice 2
   generation job for that slot's topic/difficulty), not a pick from the
   existing question bank.
2. **Auto-confirm is a lazy check on read, not a background timer.**
   Every read of a pending exam (`GET /exams/{id}`, the confirm/override
   actions) refreshes generation status and, if the review deadline has
   passed, auto-confirms right there — no new persistent background-task
   type, fully deterministic to test (monkeypatch the clock).

## A bigger simplification: no new ai endpoints for the fan-out

The Phase 2 prompt doc's shorthand describes `POST /exams/generate` +
`GET /exams/generate/{id}` as new ai-side aggregate endpoints. Building
those would mean a parallel aggregate-tracking table in `ai`
(`exam_generation_jobs`/`exam_generation_slots`) duplicating tracking
that `services/exam` needs to keep **anyway** (it has to remember which
question ended up in which slot). Instead:

- `POST /exams/schedule-ai` (an examiner-authenticated request) fans out
  by calling **Slice 2's existing, already-tested**
  `POST /questions/generate` once per slot, directly — no new ai
  endpoint.
- Status is aggregated **in exam**, by checking each slot's
  underlying job via **Slice 2's existing** `GET /questions/generate/{id}`.
- Auth for these cross-service calls: exam **forwards the calling
  examiner's bearer token** (the same pattern
  `list_published_questions` already uses when exam calls question
  service) — every check happens inside some live, freshly-authenticated
  exam-service request (the original schedule call, a later `GET
  /exams/{id}`, a confirm, or an override), so there's always a valid
  token to forward. No new internal/token-minting machinery needed.
- Overriding a slot reuses the same `POST /questions/generate` call
  again for that one slot's topic/difficulty, forwarding the acting
  examiner's token.

**Net result: the only new ai-service work in this slice is
`POST /blueprints/generate`.** Everything else is new work in
`services/exam` plus a client to call ai.

## `services/ai`: `POST /blueprints/generate`

Synchronous (one LLM call, no judge involvement, nothing stored — ai
doesn't own blueprints). Body: `{candidate_profile_id, target_role,
seniority_band, available_topics: [{id, name}]}` — `available_topics`
comes from exam (which already has an examiner token to ask question
service for the org's topic list; ai has no other way to know valid
topic ids for that org). Looks up the candidate profile from Slice 1's
own `candidate_profiles` table (no HTTP call — same service, same DB).

New `LLMClient.propose_blueprint(profile, target_role, seniority_band,
available_topics) -> BlueprintSpec`:
```python
class BlueprintSlot(BaseModel):
    topic_id: uuid.UUID
    weight: int
    difficulty_band: Literal["easy", "medium", "hard"]
    difficulty_min: int   # derived from DIFFICULTY_BANDS — exam's
    difficulty_max: int   # topic_mix needs numeric bounds, not a band
    question_count: int

class BlueprintSpec(BaseModel):
    topic_mix: list[BlueprintSlot]
    total_duration_minutes: int
    rationale: str
```
`difficulty_min`/`difficulty_max` are filled from the existing
`DIFFICULTY_BANDS` mapping (`app/generation/schemas.py`) server-side —
the LLM only picks the band per slot, never raw numeric bounds, keeping
it consistent with how Slice 2 already reasons about difficulty.
`MockLLMClient.propose_blueprint` returns a small fixed spec (2 slots
from whatever `available_topics` were passed) so the whole flow is
testable with no real key, same as every other Slice 1-3 mock.

## `services/exam`: the bulk of this slice

### New status values and a slot-tracking table

`ExamStatus` gains `PENDING_GENERATION`, `PENDING_REVIEW`, and
`GENERATION_FAILED` (alongside the existing `SCHEDULED`/`IN_PROGRESS`/
`SUBMITTED`/`EXPIRED`/`CANCELLED`). New `ExamSlotQuestion` table:
```
id                  uuid7 pk
org_id              uuid, indexed
exam_id             uuid, FK -> exams.id, ondelete=CASCADE
ordinal             int
topic_id            uuid                 -- question service's id
difficulty_band     str
generation_job_id   uuid                 -- ai's generation_jobs.id (opaque)
question_id         uuid, nullable       -- filled once ready
question_version_id uuid, nullable
status              pending | ready | failed
error               str, nullable
```
Unique on `(exam_id, ordinal)`.

### New `app/clients/ai_service.py`

Mirrors `app/clients/question_service.py`'s exact shape (`Protocol` +
`HttpAiServiceClient` + `get_ai_client()`), forwarding the caller's
`authorization` header on every call (examiner-plane, same as
`list_published_questions`):
```python
class AiServiceClient(Protocol):
    async def propose_blueprint(self, *, authorization: str, candidate_profile_id: uuid.UUID,
        target_role: str, seniority_band: str, available_topics: list[TopicRef]) -> BlueprintSpec: ...
    async def generate_question(self, *, authorization: str, topic_id: uuid.UUID,
        difficulty_band: str, language_targets: list[str]) -> uuid.UUID: ...  # returns job_id
    async def get_generation_status(self, *, authorization: str, job_id: uuid.UUID) -> GenerationStatus: ...
```
`app/clients/question_service.py` gains one more method,
`list_topics(*, authorization: str) -> list[TopicRef]` (forwards to
question's existing `GET /topics`, already examiner-gated — no question
service change needed).

### `POST /exams/schedule-ai`

Body `{candidate_email, candidate_profile_id, target_role,
seniority_band, language_targets, starts_at, ends_at}`, `WriterCtx`
(admin/author, matching `POST /exams`/`POST /blueprints` today).
1. `question_client.list_topics(authorization=<forwarded>)`.
2. `ai_client.propose_blueprint(...)` → spec.
3. `blueprints_service.create_blueprint(...)` — existing function,
   unchanged — with the spec's slots converted to the existing
   `TopicMixEntry` shape (numeric bounds already computed by ai).
4. Create the `Exam` row: `status=PENDING_GENERATION`, pinned to the new
   blueprint version — **no invite, no Redis single-use key yet**
   (`scheduling.py::schedule_exam`'s invite/email step is deferred to
   confirmation, not run here).
5. Expand `topic_mix` into flat slots (`question_count` each) and call
   `ai_client.generate_question(...)` once per slot, storing each
   returned `job_id` in a new `ExamSlotQuestion` row (`status=pending`).
6. Commit; return `{exam_id, status: "pending_generation"}`.

### Refresh (the lazy-check mechanism)

`refresh_ai_exam(session, exam, *, authorization) -> Exam`, called from
every endpoint below before it does anything else:
- If `status == PENDING_GENERATION`: for each `pending` slot, call
  `ai_client.get_generation_status(job_id, authorization=...)`; on
  `succeeded` fill `question_id`/`question_version_id`, `status=ready`;
  on `failed`, `status=failed` + `error`. If every slot is `ready` →
  `exam.status = PENDING_REVIEW`, set `review_deadline_at = now() +
  settings.ai_exam_review_timeout_seconds`. If any slot is `failed` →
  `exam.status = GENERATION_FAILED` (terminal; examiner can still
  override individual failed slots to retry, which moves the exam back
  to `PENDING_GENERATION`).
- If `status == PENDING_REVIEW` and `now() >= review_deadline_at`:
  auto-confirm (same path as an explicit confirm below).

### `GET /exams/{id}` (added if it doesn't already exist as a
single-item route — Phase 1 may only have the list endpoint)

`ReaderCtx`; calls `refresh_ai_exam` first, then returns the exam
including its slots (so the examiner can see what got generated).

### `POST /exams/{id}/confirm`

`WriterCtx`; calls `refresh_ai_exam` first; 409s unless
`status == PENDING_REVIEW`; otherwise runs the deferred invite/Redis-key/
email-send steps from `scheduling.py::schedule_exam` (extracted into a
small reusable `send_invite(session, redis, email_sender, exam) ->
Invite` so both the Phase 1 synchronous path and this deferred path
share it) and sets `status = SCHEDULED`.

### `PATCH /exams/{id}/slots/{ordinal}/regenerate`

`WriterCtx`; calls `refresh_ai_exam` first; allowed while
`status in (PENDING_GENERATION, PENDING_REVIEW, GENERATION_FAILED)`.
Calls `ai_client.generate_question(...)` again for that slot's stored
topic/difficulty (forwarding the acting examiner's token), overwrites
the slot's `generation_job_id`, clears `question_id`/`question_version_id`,
sets `status=pending`. If the exam had reached `PENDING_REVIEW` or
`GENERATION_FAILED`, it reverts to `PENDING_GENERATION` (no longer all
slots ready) until the next refresh confirms the new job succeeded.

### `start_session` — using pinned slots instead of sampling

`app/services/sessions.py::start_session`: if `ExamSlotQuestion` rows
exist for the exam (a Mode 2 exam), write `session_questions` directly
from them (already-pinned `question_id`/`question_version_id` per
ordinal) instead of calling `sampling.choose()` against a freshly
queried pool. Phase 1 (manual) exams have no `ExamSlotQuestion` rows, so
this is a strictly additive branch — existing behavior for Mode 1 exams
is untouched.

### Config

`services/exam/app/core/config.py`: `ai_service_url` (mirrors
`question_service_url`); `ai_exam_review_timeout_seconds: int = 600`
(tests override small).

## Tests

- `services/ai`: `propose_blueprint` unit tests (mock LLM, deterministic
  spec, numeric bounds derived correctly per band) + a route test for
  `POST /blueprints/generate`.
- `services/exam`: fake `AiServiceClient` (mirrors the existing fake
  question client pattern) covering: full schedule-ai flow through to
  `PENDING_REVIEW`; `start_session` uses pinned questions, never calls
  sampling, for a Mode 2 exam; explicit confirm sends the invite; a slot
  regeneration reverts `PENDING_REVIEW` → `PENDING_GENERATION` and later
  re-reaches `PENDING_REVIEW`; the auto-confirm timeout firing on a
  `GET` after the deadline (monkeypatched clock/short timeout, not a
  real wait); a failed slot yields `GENERATION_FAILED`, and overriding
  it recovers the exam.

## Non-goals for this slice

Adaptive difficulty (Slice 5), live proctoring (Slice 6), evaluation
(Slice 7), hiring reports (Slice 8). Manually-authored/Mode 1 exam
scheduling (`POST /exams`) is completely unchanged. Terraform/`deploy.yml`
wiring stays out of scope, same as Slices 1-3.
