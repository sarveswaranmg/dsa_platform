# Decisions

Short, dated records of significant technical decisions and the reasoning
behind them. Newest first.

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
