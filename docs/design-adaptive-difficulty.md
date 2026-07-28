# Design note: Adaptive difficulty engine (Phase 2, Slice 5)

## Input / output

```
Input:  session_id + question_version_id + time_elapsed_pct + verdict
        + complexity_hint (nullable)
Output: the session's updated difficulty (float 1.0-5.0) and its band
Flow:   exam's verdict consumer persists a verdict -> looks up the
        question's shown_at timestamp -> computes time_elapsed_pct ->
        calls ai's internal /difficulty/signal -> ai applies the rule
        engine against Redis-held per-session state -> exam records the
        returned band on the session (observability only, this slice)
```

## Three scope decisions confirmed with the user

1. **Engine only, no live question re-selection this slice.** Today,
   every session's questions are assigned upfront at `start_session`
   (Mode 1 via sampling, Mode 2 via Slice 4's pinned `ExamSlotQuestion`
   rows) — there is no "fetch the next question" mechanic for either
   mode, and Mode 2's whole model (examiner reviews AI-generated
   questions **before** the invite goes out) is fundamentally at odds
   with picking a question live mid-session anyway. This slice builds
   the difficulty engine as a correctly-tested, fully-wired unit — exam
   calls it after every graded verdict and records the returned band —
   but does not change what questions a candidate sees. Real adaptive
   re-selection is deferred to a later slice, once there's a coherent
   answer for how it interacts with Mode 2's review step.
2. **`complexity_hint` is accepted as an optional input, defaulting to
   the conservative "suboptimal" branch when absent.** No
   complexity-detection signal exists anywhere in the codebase yet
   (Slice 7's AI evaluation is the eventual source) — the rule engine's
   two branches are both implemented and tested by passing an explicit
   hint directly to the endpoint; exam's real call always passes `null`
   for now, so it always takes the conservative `+0.5` path. A real
   detector plugs in later without changing the contract.
3. **A new `shown_at` timestamp is added to `SessionQuestion`.** Needed
   to compute a real per-question `time_elapsed_pct`; set lazily the
   first time `GET /session/questions/{ordinal}` is called for that row
   (same lazy-set idiom as the session's existing lazy-expiry check).

## Rule engine (resolving the design note's shorthand into code)

The original four bullets ("AC in <30%... raise", "No AC past 60%...
hold", "No AC past 80%... lower") read most consistently as two
mutually-exclusive branches — verdict is `AC` or it isn't — with time
thresholds nested inside:

```python
def compute_next_difficulty(
    current: float, *, verdict: str, time_elapsed_pct: float,
    complexity_hint: Literal["optimal", "suboptimal"] | None,
) -> float:
    if verdict == "AC":
        if time_elapsed_pct < 0.30:
            delta = 1.0 if complexity_hint == "optimal" else 0.5
        else:
            delta = 0.0  # AC but not fast — hold
    else:
        delta = -1.0 if time_elapsed_pct >= 0.80 else 0.0
    return clamp(current + delta, 1.0, 5.0)
```

`verdict` is judge's summary string (`AC`/`WA`/`TLE`/`MLE`/`RE`/`CE`) —
anything other than `"AC"` takes the non-AC branch. Bounds clamp to
`[1.0, 5.0]`, matching question service's difficulty scale.
`difficulty` → band uses the same cutoffs as `DIFFICULTY_BANDS`
(`app/generation/schemas.py`): `<= 2.0` → `easy`, `<= 3.0` → `medium`,
else `hard`.

## `services/ai`: net-new Redis dependency

Currently `ai` has zero Redis footprint (Postgres, S3, SQS only). This
slice adds:

- `app/core/config.py`: `redis_url: str = "redis://localhost:6379/0"`.
- `app/core/redis.py`: singleton client + `get_redis()` FastAPI dep,
  mirroring `services/exam/app/core/redis.py` exactly.
- `app/core/redis_keys.py`: single source of truth for key shapes
  (mirrors exam's file, `ai:` prefix instead of `ex:`):
  ```python
  def difficulty_key(session_id: uuid.UUID) -> str:
      return f"ai:diff:{session_id}"
  ```
- `app/difficulty/rules.py`: `DEFAULT_DIFFICULTY = 3.0`, the clamp
  bounds, `compute_next_difficulty(...)` above, and
  `band_for_difficulty(value: float) -> str`.
- `app/services/difficulty.py`: `record_signal(redis, *, session_id,
  verdict, time_elapsed_pct, complexity_hint) -> tuple[float, str]` —
  reads current state (default `DEFAULT_DIFFICULTY` if the key is
  missing — first signal for a session starts neutral), computes the
  next value, writes it back with a generous TTL (24h — session-scoped
  ephemeral state, never meant to outlive an exam window), returns
  `(difficulty, band)`.
- `app/schemas/difficulty.py`: `DifficultySignalRequest{session_id,
  question_version_id, time_elapsed_pct: float, verdict: str,
  complexity_hint: Literal["optimal","suboptimal"] | None = None}`,
  `DifficultySignalResponse{difficulty: float, difficulty_band: str}`.
  (`question_version_id` isn't used in the calculation — kept for
  future calibration/logging, per the design note's Phase 3 remark.)
- `app/api/routes/difficulty.py`: `POST /internal/difficulty/signal` —
  **unauthenticated**, same convention as Slice 2/3's other
  `/internal/...` endpoints (already blocked at the gateway edge by
  `Route("/internal", None, Policy.BLOCKED)`). This call originates from
  exam's verdict *consumer*, a detached background loop with no live
  bearer token to forward — the same reason Slice 2 needed
  `POST /internal/questions` instead of token-forwarding.

## `services/exam`: hook into the verdict pipeline

- **Migration**: `SessionQuestion.shown_at: datetime | None` (set on
  first `GET /session/questions/{ordinal}`); `ExamSession
  .current_difficulty: float | None` and `.current_difficulty_band: str
  | None` (set after each signal call — observability only this slice,
  not consumed by question selection).
- `app/repositories/sessions.py`: `mark_shown(session, *, org_id,
  session_id, ordinal)` (no-op if already set); `get_question_by_version
  (session, *, org_id, session_id, question_version_id) ->
  SessionQuestion | None` (verdict processing only has
  `question_version_id` on the `Submission` row, not `ordinal`).
- `app/services/sessions.py::get_question_content`: calls `mark_shown`
  before returning content.
- `app/clients/ai_service.py`: new method on the existing
  `AiServiceClient` (Slice 4) —
  `send_difficulty_signal(*, session_id, question_version_id,
  time_elapsed_pct, verdict, complexity_hint) -> DifficultySignal` — no
  `authorization` param (internal/unauthenticated, like
  `question_service.py`'s `list_published_questions_internal`).
- `app/services/verdicts.py::process_verdict_message`: gains a required
  `ai_client: AiServiceClient` parameter. After persisting the verdict
  and committing, if `submission.mode == "submit"` (a trial `run`
  doesn't represent a graded attempt) and `submission.session_id` is
  not `None`:
  1. Look up the `ExamSession` (for `started_at`/`deadline_at`) and the
     `SessionQuestion` (for `shown_at`) via the new repo function.
  2. If `shown_at` is `None` (defensive — shouldn't happen), skip the
     signal call.
  3. `allotted_seconds = (deadline_at - started_at).total_seconds() /
     len(session's questions)` — the session's actual duration split
     evenly across its questions (no separate blueprint lookup needed).
  4. `time_elapsed_pct = (now - shown_at).total_seconds() /
     allotted_seconds`.
  5. Call `ai_client.send_difficulty_signal(...)`
     (`complexity_hint=None` — no detector exists yet), wrapped in
     `try/except` so an unreachable `ai` never breaks the verdict
     idempotency boundary (log a warning, continue).
  6. On success, set `exam_session.current_difficulty`/
     `current_difficulty_band` and commit.
- `app/messaging/consumer.py::run_verdict_consumer`: constructs an
  `ai_client = get_ai_client()` once and threads it into
  `process_verdict_message`.
- `app/core/config.py`: `ai_service_url` already exists (Slice 4) —
  reused as-is.

## Tests

- `services/ai`: `test_difficulty_rules.py` — every branch (AC fast
  optimal `+1`, AC fast suboptimal/null `+0.5`, AC slow `hold`, non-AC
  `<80%` `hold`, non-AC `>=80%` `-1`), bounds (`clamp` never below `1.0`
  or above `5.0`), `band_for_difficulty` cutoffs.
  `test_difficulty.py` (route) — first signal for a session starts from
  `DEFAULT_DIFFICULTY`; state persists across repeated signals for the
  same `session_id` (Redis round-trip); different `session_id`s don't
  interfere.
- `services/exam`: extend `test_submissions.py`'s verdict-processing
  tests with a fake `AiServiceClient.send_difficulty_signal` — a
  `submit`-mode AC verdict calls it with a correctly computed
  `time_elapsed_pct` and stores the returned band on the session; a
  `run`-mode submission never calls it; an unreachable `ai` (fake
  raises) doesn't prevent the verdict from persisting.
  `test_sessions.py`: `GET /session/questions/{ordinal}` sets
  `shown_at` only once (idempotent on repeat calls).

## Non-goals for this slice

Live/dynamic question re-selection (deferred, see scope decision #1),
real complexity detection (Slice 7), IRT calibration from real session
data (Phase 3, explicitly called out in the original design shorthand).
