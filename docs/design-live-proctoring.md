# Design note: Live proctoring + mid-exam follow-ups (Phase 2, Slice 6)

## Input / output

```
Input:  candidate code snapshots (every 30s) + submissions + verdicts,
        streamed live; a proctor-authored constraint edit mid-exam
Output: an append-only, replayable event stream per session; a proctor
        live-view of a candidate's session; a new question version with
        updated test cases when a follow-up is pushed, with grading
        binding to the new version from that point on
Flow:   candidate WS <-> gateway <-> exam (code_snapshot in, verdict/
        followup_pushed out) ; proctor WS <-> gateway <-> exam (observer,
        receives the same session's event stream live)
```

## Three scope decisions confirmed with the user

1. **Full scope in one pass** — gateway WebSocket proxying, the
   `session_event` table, all event types (`question_assigned`,
   `code_snapshot`, `submission`, `verdict`, `followup_pushed`), the
   proctor live channel, the follow-up endpoint, session replay, and
   frontend WS wiring (the candidate-side banner component,
   `RequirementsChangedBanner`, already exists as a built seam from
   Phase 1 — this slice wires a real WS event into it).
2. **Real WebSocket proxying in the gateway** (not a direct-to-exam
   bypass) — keeps the "gateway is the only published entry point"
   invariant every prior slice has held, and matches
   `docs/architecture.md` §4.1/§7 exactly. The gateway gains a new
   outbound WS client dependency (`websockets`) since `httpx` cannot
   proxy WebSockets.
3. **Follow-up test cases: extend the factory to work by question
   lineage.** Slice 3's on-demand factory requires an exact
   `generation_jobs` row keyed to the specific `question_version_id` —
   which a brand-new copy-on-write version never has. `ai` gains a
   lineage lookup (latest succeeded job for the *question*, any
   version) so a follow-up on an AI-descended question can still
   generate+validate real test cases. A follow-up on a purely
   manually-authored question has no reference/brute-force solution to
   validate against at all (same restriction Slice 3 already
   established) — its new version's test cases are copied forward from
   the prior version unchanged, no new differential validation.

## `services/exam`: event sourcing spine

### New `session_event` table

```
id                  uuid7 pk
org_id              uuid, indexed
session_id          uuid, FK -> exam_sessions.id, ondelete=CASCADE, indexed
seq                 int              -- strictly increasing per session
type                str              -- question_assigned | code_snapshot |
                                     -- submission | verdict | followup_pushed
payload             jsonb
question_version_id uuid, nullable   -- the version this event concerns, if any
created_at          timestamptz
```
Unique on `(session_id, seq)`. `seq` is assigned at insert time via
`COALESCE(MAX(seq), 0) + 1` scoped to the session, inside the same
transaction as the write that produces the event — matches this
codebase's existing tolerance for small races (single candidate +
occasional proctor writes to one session; not worth a distributed
sequence generator for this volume).

### Emission points (all via one `app/services/session_events.py::emit`)

- `question_assigned` — once per `SessionQuestion` row, at the end of
  `start_session` (one event per assigned question).
- `code_snapshot` — from the candidate WebSocket connection, whenever a
  `code_snapshot` frame arrives (candidate editor pushes its current
  buffer every 30s; see WS section). Payload: `{ordinal, language,
  source}`.
- `submission` — in `submissions_service.create_and_enqueue`, right
  after the submission row commits.
- `verdict` — in `verdicts.py::process_verdict_message`, right after the
  verdict commits (same place the Slice 5 difficulty signal already
  hooks in).
- `followup_pushed` — emitted by the new follow-up endpoint (below),
  payload `{previous_version_id, new_version_id, summary}` — the exact
  shape the frontend's existing `RequirementsChange` type expects.

### WebSocket hub (`app/ws/`, new)

Two routes, both plain FastAPI `@router.websocket(...)`:

- **Candidate channel** — `WS /candidate/session/ws`. Auth: native
  browser `WebSocket` cannot set custom headers on the handshake, so the
  candidate's exam token is passed as a query parameter
  (`?token=...`), verified with the same `decode_candidate_exam_token`
  logic `get_candidate_context` already uses. On connect: replays
  nothing (candidate already has REST endpoints for current state);
  subscribes to a per-session Redis pub/sub channel
  (`ex:session-events:{session_id}`) for outbound push (`verdict`,
  `followup_pushed`); reads inbound `{"type": "code_snapshot", "ordinal":
  ..., "source": ...}` frames from the candidate and calls
  `session_events.emit(..., type="code_snapshot", ...)`.
- **Proctor channel** — `WS /sessions/{session_id}/proctor-ws`. Auth:
  same query-param-token approach, but decodes an **examiner** access
  token and requires `Role.PROCTOR` (mirrors `require_role(Role.PROCTOR)`
  — the dependency itself doesn't change, just how it's invoked from a
  WS handshake instead of an HTTP request; `auth.py`-equivalent checks
  work unchanged since they only need the header/query value, not a
  `Request` object). Observer-only: subscribes to the same
  `ex:session-events:{session_id}` Redis channel and simply forwards
  every event to the proctor as JSON frames — never accepts inbound
  frames that mutate state (proved by a test: sending a frame from the
  proctor socket has no effect and isn't treated as a submission).

Redis pub/sub (new usage — Redis today is only used for
key-value session/invite state, never pub/sub) is the fan-out
mechanism: `session_events.emit` does the DB insert *and* publishes the
same payload to `ex:session-events:{session_id}`, so both a live proctor
and (future) multiple candidate tabs see it immediately without polling
the DB.

### `POST /sessions/{id}/followup` (proctor only)

`WriterCtx` narrowed to `require_role(Role.PROCTOR)`. Body:
`{ordinal, modified_constraints_md}`. Service
(`app/services/followups.py`, new):
1. Look up the session's `SessionQuestion` at `ordinal` → get
   `question_id` (not just `question_version_id` — needed to call
   question service's fork-by-question-id flow).
2. Call question service's new internal endpoint (below) to fork a
   draft version with the edited constraint (not yet published).
3. Call `ai`'s test-case factory (synchronous variant, ~30s timeout —
   the exact variant Slice 3 built for "on-demand" use) with the new
   `question_version_id` **and** the original `question_id` as a
   lineage hint. `ai` looks up the latest succeeded `generation_jobs`
   row for that `question_id` (any version) and reuses its
   reference/brute-force solution to generate+validate test cases,
   attached to the new version via question's existing internal
   `POST /internal/questions/{id}/test-cases` (Slice 3's endpoint,
   unchanged — attaching test cases while the version is still an
   unpublished draft mutates it in place rather than forking again,
   avoiding a double-fork).
4. Publish the finished draft (question service's new internal publish
   endpoint) — sealing it as immutable, consistent with "editing a
   published question creates a new version."
5. Update `SessionQuestion.question_version_id` to the new version (new
   repo function — this mutation doesn't exist today; grading from this
   point on binds to the new version, matching the architecture note's
   "grading binds to version active at submission time").
6. Emit `followup_pushed` (DB row + Redis publish, reaching the
   candidate's live WS connection and the proctor's).

### New question-service internal endpoints (unauthenticated, trusted-network,
already blocked at the gateway edge — same convention as every prior slice's
`/internal/...` additions)

- `POST /internal/questions/{id}/followup-draft` — body
  `{org_id, constraints_md}`; calls `ensure_mutable_version` + sets
  `constraints_md`, does **not** publish. Returns the draft version's
  content (same shape as `get_version_content`).
- `POST /internal/questions/{id}/publish` — body `{org_id}`; thin
  internal mirror of the existing examiner `POST /questions/{id}/publish`
  route (same service function, `questions_service.publish_question`,
  just reachable without a bearer token — the proctor's role was already
  checked by exam before this call happens).

### `GET /sessions/{id}/replay` (reviewer only)

`require_role(Role.REVIEWER)` (mirrors the existing `ResultsCtx` role
set, narrowed to reviewer since this is post-hoc audit, not proctoring).
Returns all `session_event` rows for the session ordered by `seq`.

## `services/ai`: lineage-based factory lookup

- `app/repositories/generation_jobs.py`: new `get_succeeded_by_question
  (session, *, org_id, question_id) -> GenerationJob | None` — same shape
  as the existing `get_succeeded_by_version`, ordered by `created_at`
  descending, `limit(1)`.
- `app/schemas/testcase_generation.py`: `TestCaseGenerationRequest` gains
  an optional `source_question_id: uuid.UUID | None = None`.
- `app/services/testcase_generation.py::start_factory_job`: if
  `source_question_id` is given, look up via `get_succeeded_by_question`
  instead of `get_succeeded_by_version`; everything downstream
  (`_build_diff_job`, `finalize_factory_result`) is unchanged — it
  already just needs a `GenerationJob` row with a
  `reference_solution`/`brute_force_solution`/`draft`, regardless of
  which version produced it. Test cases still get attached to the
  request's `question_version_id` (the new draft version), not the
  source job's original version.
- **New internal endpoint** (gap caught in review — the existing
  `POST /test-cases/generate` is `require_role(Role.ADMIN, Role.AUTHOR)`,
  and the proctor's follow-up flow has no such token to forward, same
  problem already solved for question service's publish/update routes):
  `POST /internal/test-cases/generate`, unauthenticated, mirroring
  `app/api/routes/difficulty.py`'s exact shape — body carries `org_id`,
  `question_version_id`, `source_question_id`; always runs the
  synchronous variant (a follow-up needs the result inline, within the
  ~30s budget, to attach test cases before publishing). `exam`'s
  `ai_service.py` client gets a new `run_followup_factory(...)` method
  hitting this route directly (no `authorization` param, same pattern as
  `send_difficulty_signal`).

## `services/gateway`: WebSocket proxying (new capability)

- New dependency: `websockets` (outbound WS client — `httpx` cannot
  proxy WebSockets).
- New route (Starlette `@app.websocket_route` or FastAPI
  `@app.websocket(...)`, alongside the existing catch-all HTTP route):
  matches the same `match_route` table (a WS-scope request still has a
  `path`), so `/candidate/session/ws` and `/sessions/{id}/proctor-ws`
  resolve to `Upstream.EXAM` via the existing `/candidate` and `/exams`
  (or a new `/sessions` — see routing note below) prefixes — no new
  routing-table concept, just a scope that isn't `http`.
- Handshake: read the token from the query string (`websocket.query_params
  ["token"]`), run it through the same `authorise(...)` primitives
  already used for HTTP (confirmed request-object-agnostic — they take
  plain `policy`/`authorization`/`client_ip` values), `await
  websocket.accept()` only if authorized, else close with a policy
  violation code before accepting.
- Relay: open an outbound `websockets` connection to
  `ws://exam:8000/<same path>` forwarding the token, then run two
  concurrent `asyncio` tasks pumping frames in each direction until
  either side closes.
- **Routing note**: the proctor route's path is `/sessions/{id}/proctor-ws`,
  a new top-level prefix not covered by the existing `/exams` entry.
  Add `Route("/sessions", Upstream.EXAM, Policy.EXAMINER)` to the
  gateway's route table (mirrors `/exams`) — the candidate WS route
  reuses the existing `/candidate` prefix/`Policy.CANDIDATE` unchanged.

## Frontend: wiring the existing seam

- New `frontend/src/api/candidateSocket.ts` — thin native-`WebSocket`
  wrapper (no new npm dependency, per `CLAUDE.md`'s "native WebSocket"
  stack choice already confirmed by the earlier research pass): opens
  `wss://.../candidate/session/ws?token=...`, sends a `code_snapshot`
  frame every 30s with the current editor buffer, and on an incoming
  `followup_pushed` frame calls back into `ExamRoomPage` with a
  `RequirementsChange` object — populating the *already-built*
  `<RequirementsChangedBanner change={...} />` prop (`ExamRoomPage.tsx`
  currently hardcodes `change={null}`; this slice is what finally
  supplies a real value). On an incoming `verdict` frame, invalidates
  the relevant TanStack Query submission cache key so the existing
  1.5s-poll-until-terminal UI updates immediately instead of waiting for
  its next poll tick (a nice-to-have side benefit of the same
  connection, not a new component).
- No changes to `RequirementsChangedBanner.tsx` itself — it was built
  exactly for this.

## Tests

- `services/exam`: event ordering (`seq` strictly increasing, concurrent
  writers don't collide within the test's scope); proctor WS isolation
  (a frame sent by the proctor socket never creates a submission or any
  other state change — observer-only, asserted by inspecting DB state
  after); follow-up creates a new version and `SessionQuestion` points
  at it; a submission made *after* a follow-up grades against the new
  version's test cases, one made *before* still resolved against the
  old version's; replay returns the complete ordered stream, gated to
  `Role.REVIEWER` (other roles 403).
- `services/ai`: `get_succeeded_by_question` returns the latest
  succeeded job across versions; `start_factory_job` with
  `source_question_id` set successfully generates against a job found
  via lineage, and 404s the same way as today when no succeeded job
  exists at all for that question.
- `services/question`: the two new internal endpoints (`followup-draft`,
  `publish`) — draft creation forks correctly, doesn't publish; a
  second draft call before publishing mutates in place (no
  double-fork); publish flips `published_version_id`.
- `services/gateway`: WS handshake authorization (valid token accepted,
  missing/invalid token rejected before `accept()`, matching the
  existing HTTP auth-plane test conventions); a smoke test that frames
  written to one side of the relay arrive on the other (using a fake
  upstream WS server, not a real exam instance).
- `frontend`: `candidateSocket.ts` unit tests (mocking the global
  `WebSocket`) for the 30s snapshot cadence and the `followup_pushed` →
  banner-prop wiring; no changes needed to
  `RequirementsChangedBanner.test.tsx` (already covers the component
  itself).

## Non-goals for this slice

AI evaluation (Slice 7), hiring reports (Slice 8), Redis-based WS
presence beyond the single pub/sub channel already described (multi-pod
fan-out for horizontal scaling is a Phase 3 concern per
`docs/architecture.md` §8), reconnection/backoff polish beyond "the
candidate's REST endpoints remain the source of truth on reload" (the
WS connection is a live-update convenience layer, not the only way to
get state — consistent with Phase 1's existing resume-after-disconnect
design, which stays REST-driven).
