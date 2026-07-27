# Decisions

Short, dated records of significant technical decisions and the reasoning
behind them. Newest first.

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
