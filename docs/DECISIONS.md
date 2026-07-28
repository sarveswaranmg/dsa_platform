# Decisions

Short, dated records of significant technical decisions and the reasoning
behind them. Newest first.

## Live proctoring: real WS proxying at the gateway, event-sourced sessions, lineage-based follow-up test cases (2026-07-29)

**Decision:** Phase 2 Slice 6 adds WebSocket infrastructure end to end —
`services/exam` gains a candidate channel (`WS /candidate/session/ws`,
bidirectional: accepts `code_snapshot` frames, pushes `verdict`/
`followup_pushed`) and a proctor channel (`WS
/sessions/{id}/proctor-ws`, observer-only), both backed by Redis pub/sub
(`ex:session-events:{session_id}`) for live fan-out. `services/gateway`
proxies both **as real WebSocket connections**, not a direct-to-exam
bypass — a new `app/ws_proxy.py` validates the handshake (token +
role/policy, via the same `authorise()` primitives the HTTP path already
uses) before `accept()`, then pumps frames both directions via
`websockets` as an outbound client. This preserves the
"gateway is the only published entry point" invariant every prior slice
has held, at the cost of a new `websockets` dependency in gateway (`httpx`
cannot proxy WebSockets).

Every session is now event-sourced: a new append-only `session_events`
table (`seq` per session, `type`, `payload`, optional
`question_version_id`) records `question_assigned`, `code_snapshot`,
`submission`, `verdict`, and `followup_pushed`, replayable in full via
`GET /sessions/{id}/replay` (`Role.REVIEWER`-gated). A proctor can push a
mid-exam follow-up (`POST /sessions/{id}/followup`, `Role.PROCTOR`-gated)
that forks the question's immutable version (copy-on-write, question
service), regenerates test cases, republishes, and re-points the
session's assigned question — grading of any submission from that point
on binds to the new version automatically, since submission already
reads `question_version_id` fresh off the session at submit time.

**Follow-up test-case regeneration works by lineage, not exact version
match.** A follow-up's forked version has no `generation_jobs` row of
its own (that row belongs to whichever version was originally
AI-generated), so `ai` gained `get_succeeded_by_question` — latest
succeeded job for a `question_id` across *all* its versions — and a new
unauthenticated `POST /internal/test-cases/generate` route (mirroring
`app/api/routes/difficulty.py`'s existing shape) so exam's follow-up flow
can call it without an examiner bearer token. A purely manual (Phase 1)
question has no AI lineage at all: `push_followup` wraps the factory
call in try/except and never blocks on failure, since
`ensure_mutable_version`'s copy-on-write already carries the prior
version's test cases forward (S3 keys are immutable uploads, safe to
reuse) — so a follow-up on a manual question still ships usable, if
unchanged, test cases.

**Why real WS proxying over a bypass:** a direct-to-exam WebSocket would
be the first thing in this codebase reachable without going through the
gateway's auth/rate-limit/routing table — confirmed with the user this
was worth the extra `websockets` dependency and proxy code rather than
carving out an exception to the "gateway is the only edge" rule.

**Why query-param tokens for the WS handshake:** the native browser
`WebSocket` API cannot set custom headers, so both channels take
`?token=...` instead of `Authorization: Bearer`, decoded directly via the
existing `decode_candidate_exam_token`/`decode_access_token` functions
(already request-object-agnostic, reusable as-is outside the
`HTTPBearer`/`Depends` extraction the HTTP routes use).

**Status:** Implemented and verified end-to-end through the real stack
(gateway → exam WS relay in both directions, proctor push → candidate
live notification → grading against the new version → full ordered
replay). One testing-infrastructure limitation surfaced, not a product
gap: Starlette's `TestClient` runs the ASGI app in a background thread
with its own event loop, so the exam service's savepoint-based
`db_session` test fixture (bound to the main test loop) cannot be shared
with it — `httpx-ws` was tried and abandoned (`httpx.ASGITransport`
hardcodes `scope["type"] = "http"`, no WebSocket scope support at all).
Exam's new WS pytest coverage is therefore scoped to handshake-only
rejection paths (missing/invalid token, wrong role) that never reach a
DB query; the full connected flow (session lookups, event recording,
bidirectional forwarding) is proven by the real end-to-end run above
instead of a mocked unit test.

## Adaptive difficulty: engine only, no live question re-selection yet (2026-07-28)

**Decision:** Phase 2 Slice 5's difficulty engine (`ai`'s new `POST
/internal/difficulty/signal`, Redis-backed per-session state, static
rule engine) is built and fully wired — `exam`'s verdict consumer calls
it after every graded (`mode=submit`) verdict and records the returned
band on `ExamSession.current_difficulty`/`current_difficulty_band` — but
nothing yet uses that band to change what question a candidate sees.
Confirmed explicitly with the user: today every session's questions are
still assigned upfront at `start_session` (Mode 1 sampling or Mode 2's
Slice-4 pinned slots), and there's no "fetch the next question" mechanic
for either mode. Mode 2's own model — the examiner reviews AI-generated
questions **before** the invite goes out — is fundamentally at odds with
picking a question live mid-session anyway, so real adaptive
re-selection is deferred to a later slice once there's a coherent answer
for that interaction.

**Rule engine** collapses the design note's four bullets into two
mutually-exclusive branches on `verdict == "AC"` (`services/ai/app/difficulty/rules.py`):
an accepted, fast (`<30%` of the question's time budget) solution raises
difficulty (`+1` if `complexity_hint == "optimal"`, `+0.5` otherwise —
including `None`); anything else holds, except a failed attempt at
`>=80%` of the time budget, which lowers by `1`. `complexity_hint` is
accepted as an optional input and both branches are unit-tested via an
explicit hint, but `exam`'s real call always passes `None` — no
complexity-detection signal exists anywhere yet (Slice 7's AI evaluation
is the eventual source), so production behavior always takes the
conservative `+0.5` path today.

**New per-question timing**: `SessionQuestion.shown_at` (nullable,
additive migration) is set lazily the first time `GET
/session/questions/{ordinal}` is called for that row — no such signal
existed before this slice. `time_elapsed_pct` is computed as elapsed time
since `shown_at` divided by the session's total duration split evenly
across its question count (`(deadline_at - started_at) / num_questions`)
— no separate blueprint lookup needed.

**`send_difficulty_signal` is unauthenticated** (`/internal/difficulty/signal`),
unlike every other method on `exam`'s `ai_service.py` client (which
forward the calling examiner's bearer token) — because this call
originates from `exam`'s detached verdict-consumer background loop,
which has no live token to forward, the same reason Slice 2 needed
`POST /internal/questions` instead of token-forwarding. Already blocked
at the gateway edge by the existing `Route("/internal", None,
Policy.BLOCKED)`.

**`services/ai` gained a net-new Redis dependency** (previously
Postgres/S3/SQS only) — mirrors `services/exam`'s `core/redis.py`/
`redis_keys.py` shape exactly, `ai:` key prefix instead of `ex:`. State
is a single float per session with a 24h TTL — ephemeral, never meant to
outlive an exam window, no Postgres row.

**Status:** Implemented and verified end-to-end through the real stack
(gateway → exam → ai → Redis → exam): a real judge-graded AC submission
correctly raised `ExamSession.current_difficulty` from the 3.0 default to
3.5 (`+0.5`, fast AC with no complexity hint) and stored `"hard"` as the
band (cutoffs `<=2.0` easy / `<=3.0` medium / else hard — a new,
standalone partition, not a reuse of `generation/schemas.py`'s
`DIFFICULTY_BANDS`, which is only ever a per-band validation range and
isn't a clean partition itself), with Redis's `ai:diff:{session_id}`
matching exactly.

## Mode 2 scheduling: reuse Slice 2's endpoints via token-forwarding instead of new ai aggregate endpoints (2026-07-28)

**Decision:** Phase 2 Slice 4's `POST /exams/schedule-ai` does not call any
new `ai`-side aggregate endpoints for the per-slot generation fan-out/status
poll that the Phase 2 prompt doc's shorthand (`POST /exams/generate` + `GET
/exams/generate/{id}`) implied. Building those would mean a parallel
aggregate-tracking table in `ai` (`exam_generation_jobs`/
`exam_generation_slots`) duplicating tracking `services/exam` needs to keep
anyway (it has to remember which question ended up in which slot). Instead,
`exam` fans out by calling Slice 2's existing, already-tested `POST
/questions/generate` once per slot directly, and aggregates status itself
by polling each slot's job via Slice 2's existing `GET
/questions/generate/{id}` — both new methods on a new
`app/clients/ai_service.py` (mirrors `question_service.py`'s
`Protocol`/`Http.../get_*_client()` shape exactly). The only new `ai`-side
work this slice needed was a synchronous `POST /blueprints/generate` (one
LLM call, nothing stored — `ai` doesn't own blueprints).

Every cross-service call forwards the acting examiner's bearer token
(`request.headers["authorization"]`, the same pattern
`app/api/routes/blueprints.py`'s `sample_blueprint` already used for
`question_service.py`) rather than minting a fresh token — every entry
point (`schedule-ai`, a later `GET`, confirm, or a slot override) runs
inside some live, freshly-authenticated request, so a valid token to
forward is always available. No new internal/token-minting machinery
needed for the examiner plane.

**Two scope decisions confirmed with the user:** overriding a slot
regenerates it via a fresh Slice 2 generation job (not a pick from the
existing question bank), and auto-confirm is a **lazy check on read**, not
a background timer — `refresh_ai_exam` runs first on every Mode 2 endpoint
(`GET /exams/{id}`, confirm, regenerate) and auto-confirms right there once
`review_deadline_at` has passed. This avoids a new persistent background-
task type and stays fully deterministic to test (the deadline is a stored
timestamp, movable directly in a test without monkeypatching the clock).

**Schema notes:** `Exam.status` is a native Postgres enum
(`sqlalchemy.Enum` with `values_callable`) — the only column in this
codebase using one — so adding `pending_generation`/`pending_review`/
`generation_failed` required a hand-written migration
(`op.execute("ALTER TYPE exam_status ADD VALUE IF NOT EXISTS ...")`); no
prior migration in this repo had done this before. Postgres 16 allows this
inside a normal transactional migration (the pre-12 "not in a transaction
block" restriction no longer applies), confirmed by applying it directly
against the dev stack. Downgrade leaves the added values in place —
Postgres has no `DROP VALUE`, only a full type rebuild, which isn't worth
it for a migration nobody has shipped yet. The new `ExamSlotQuestion` table
uses a plain `String` status column instead, matching this codebase's
default convention (`SessionStatus`, `GenerationStatus`, etc.) — native
enums are the exception here, not the rule.

**Status:** Implemented and verified end-to-end through the real stack
(gateway → exam → ai → question, with judge-gen actually generating and
differentially validating all 4 slots of a 2-topic, question_count=2 mock
blueprint) — schedule-ai → pending_generation → pending_review → confirm →
scheduled, plus the pinned-slot bypass in `start_session` confirmed via the
exam test suite (a Mode 2 exam's `session_questions` come straight from
`ExamSlotQuestion` rows, never `sampling.choose()`).

## Test-case factory: AI-generated questions only, reuses Slice 2's judge-gen lane as-is (2026-07-28)

**Decision:** Phase 2 Slice 3's test-case factory (`POST
/test-cases/generate`) only supports question versions produced by a
**succeeded** Slice 2 generation job — confirmed explicitly with the
user. It looks one up in `ai`'s own `generation_jobs` table by
`question_version_id`; manually-authored (Phase 1) questions have
neither a reference/brute-force solution nor a structured `input_spec`
to validate candidates against, so they 404. Extending to
examiner-supplied solutions for manual questions (per
`docs/architecture.md`'s "reference solution the proctor supplies or
approves") is deferred to a later slice.

Submitting candidates for differential testing reuses Slice 2's
`DiffJob`/`DiffResult`/`gen_runner` machinery **unchanged** in shape, with
two small additive fields on the wire contract: `capture_agreement_outputs`
(the factory needs the reference's output on agreement — it becomes a
kept case's expected output — where Slice 2 only needed it on
disagreement, for the discard log) and `results_queue` (lets the
on-demand synchronous variant use a throwaway per-request reply queue
instead of the shared async one). Both default to Slice 2's original
behavior, so nothing there changed. `sandbox.py` and judge-live
(`worker.py`/`runner.py`) remain untouched.

Kept cases are stored via a new `test_case_generation_jobs` table — not
a reuse of `generation_jobs.discard_log`, despite that being the Phase 2
prompt doc's original shorthand — because that row's status is already
terminal (`succeeded`) by the time a factory job runs against it, and
overloading it with a second, independent job lifecycle would conflate
two different concerns.

**On-demand (synchronous) variant caveat:** discovered during end-to-end
verification, not by unit tests: question service's presigned test-case
upload URLs are generated for browser/host consumption
(`s3_presign_endpoint_url`), so PUTting from *inside* the `ai` container
to the exact URL returned failed (`localhost:4566` doesn't resolve
in-network). Fixed by rewriting the URL's host:port to ai's own
`s3_endpoint_url` before PUTting (`app/services/testcase_generation.py`
`_in_network_s3_url`) — already environment-correct on both sides
(`localstack:4566` in containers, `localhost:4566` for tests on the
host), and a no-op in production (real S3 URLs never contain
`localhost:4566`). A first attempt hardcoded the literal string swap and
broke host-run tests; the fix instead derives the target host from
`get_settings().s3_endpoint_url` via `urlsplit`/`urlunsplit`, which
adapts correctly in both places.

**Status:** Implemented and verified end-to-end through the real stack,
including the synchronous variant's real poll loop and timeout path.

## Question generation: separate judge-gen lane reusing the sandbox unchanged (2026-07-28)

**Decision:** Phase 2 Slice 2's differential testing (reference vs.
brute-force solution, compared to each other on ~100 generated inputs)
runs through a **new, fully separate** SQS lane — `dsa-judge-gen` /
`dsa-judge-gen-results` — consumed by a **new worker process**
(`services/judge/app/gen_worker.py` + `gen_runner.py`), never the
existing judge-live queues or `worker.py`/`runner.py`. Container
invocation glue (`_run_container`, `_name`, `_image`, `SOURCE_FILENAME`)
was extracted from `runner.py` into `exec_common.py` so the new path
reuses it instead of duplicating it; `sandbox.py` (the actual security
contract — network-none, read-only rootfs, non-root, resource limits)
was **not touched at all**. Reference/brute-force solutions are
generated and validated in Python only, regardless of how many
`language_targets` are requested for starter code — proving the
problem's logical soundness once is sufficient; starter code in other
languages is unvalidated scaffolding, same as any other question-bank
content.

Because the generation results consumer has no live examiner bearer
token by the time a job succeeds (could be minutes after the original
request, well past the 15-minute access token TTL), `services/question`
gained a new **internal** endpoint (`POST /internal/questions`,
org_id in the body, no auth) rather than storing/reusing a token — same
trusted-network-only convention as its existing `/internal/...` routes,
already blocked at the gateway edge.

**Why not extend the judge-live queue/worker instead:** differential
testing has no "expected output" to compare against (it compares two
fresh outputs to each other) and needs two solutions compiled per job
instead of one — forcing that shape into `SubmissionJob`/`runner.py`
would have complicated the hot path candidates depend on. A wholly
separate lane also means heavy generation traffic can never delay a
candidate's real submission, which was an explicit Phase 2 requirement
("judge-gen lower priority than judge-live, never mix them").

**Status:** Implemented and verified end-to-end through the real stack
(gateway → ai → judge-gen → ai → question). One pre-existing gap
surfaced during that verification, not introduced by this slice: neither
`services/judge`'s Dockerfile-built image contains a `docker` CLI binary
(the `docker.io` apt package installed with `--no-install-recommends`
omits it on this platform) — so the containerized `judge`/`judge-gen`
services can't actually launch sandboxed containers via `docker compose
up` here. This was already worked around for `judge` before Slice 2
existed (`docs` and `scripts/e2e.py` both say to run
`cd services/judge && uv run python -m app.worker` on the host on
macOS); `judge-gen` inherits the same workaround
(`uv run python -m app.gen_worker`). Fixing the Dockerfile itself is
out of scope for this slice — flagged for a follow-up.

## Profile ingestion: fire-and-forget asyncio task, mock LLM/GitHub by default (2026-07-27)

**Decision:** The new `services/ai`'s profile ingestion job (Phase 2 Slice
1) runs as a single `asyncio.create_task` fired right after `POST
/profiles` commits, not a persistent SQS consumer. `LLMClient` and
`GitHubClient` both default to deterministic mock implementations
(`LLM_BACKEND=mock`, `GITHUB_BACKEND=mock`) rather than real Anthropic/
GitHub calls.

**Why:** This slice is one job per profile with no queue semantics to
speak of (no retry-from-a-broker need, no fan-out) — the exam service's
existing verdict consumer (`services/exam/app/messaging/consumer.py`)
solves a different problem (durable, replayable judge verdicts) and would
be overkill here. Anthropic/GitHub calls default to mocks per an explicit
choice made when starting Phase 2: no real API key was wired up for this
session, so dev/CI never need one and never make a real network call or
incur cost. Both are swappable later (`LLM_BACKEND=anthropic` with
`ANTHROPIC_API_KEY` set; `GITHUB_BACKEND=real`) without touching callers,
since both sit behind a `Protocol` (`app/llm/client.py`,
`app/clients/github.py`), the same shape as the existing `EmailSender`
protocol.

**Status:** Implemented. Revisit the asyncio-task choice if a later
Phase 2 slice needs retryable/durable generation jobs — Slices 2 and 3
(question generation, test-case factory) explicitly use a `judge-gen` SQS
lane instead, precisely because they submit work to the judge pipeline
and need that durability.

## Judge node isolation: dedicated pool + gVisor, Firecracker as stretch (2026-07-23)

**Decision:** Production judge workers run on a dedicated node pool with
nothing else co-tenanted, and their sandbox containers run under gVisor
(`--runtime=runsc`, `JUDGE_RUNTIME=gvisor`) rather than plain runc.
Firecracker microVMs remain a documented stretch goal, not yet built.

**Why:** The judge worker mounts `/var/run/docker.sock` to launch sibling
sandbox containers (DooD) — that socket is effectively host root access.
The sandbox containers themselves are already hardened (no network,
read-only rootfs, non-root user, dropped capabilities, resource limits —
see `services/judge/app/sandbox.py` and `services/judge/tests/test_security.py`),
but a kernel-level container-escape bug in runc would still reach the host.
gVisor intercepts syscalls in a userspace kernel, shrinking that blast
radius substantially without requiring a rewrite of the existing sandbox
contract. Node-pool isolation means that even a full escape only ever
reaches other judge workers, never gateway/exam/question/postgres/redis.

**Status:** `JUDGE_RUNTIME` is wired end-to-end (`services/judge/app/config.py`,
`sandbox.py`, `infra/docker-compose.yml`) and defaults to `runc` everywhere
today, since gVisor isn't installed on dev machines or (yet) in CI. Enabling
it in production requires: gVisor (`runsc`) installed and registered with
Docker on the node image/AMI, the judge ASG's launch template setting
`JUDGE_RUNTIME=gvisor`, and — per the "dedicated node pool" half of this
decision — that ASG must run no other workload.
