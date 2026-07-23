# Decisions

Short, dated records of significant technical decisions and the reasoning
behind them. Newest first.

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
