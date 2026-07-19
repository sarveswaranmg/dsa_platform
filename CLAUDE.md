DSA Exam Platform

Adaptive, invite-only DSA assessment platform. Examiners compose exams from a
candidate's role/experience profile, AI generates validated test cases, and
examiners can push live follow-ups mid-exam over WebSocket.

Read docs/architecture.md before any non-trivial task.

Stack


Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic
Data: Postgres 16 (system of record), Redis (sessions, presence, rate limits), S3/MinIO (submissions, large test-case files)
Queue: SQS-compatible (localstack in dev) for the judge pipeline
Frontend: React 18 + TypeScript + Vite, Monaco editor, native WebSocket
Infra: Docker Compose for dev; Terraform stubs in infra/
Tests: pytest + pytest-asyncio (backend), Vitest + React Testing Library (frontend)


Repo layout

services/gateway/    # routing, JWT validation, rate limiting
services/exam/       # blueprints, sessions, invites, WebSocket hub
services/question/   # question bank, taxonomy, AI test-case factory
services/judge/      # queue consumer + sandboxed execution workers
frontend/            # examiner console + candidate exam UI
infra/               # docker-compose, Terraform, localstack config
docs/                # architecture.md, DECISIONS.md, design notes

Hard rules


Services NEVER import each other's code. Communication is HTTP or queue only.
Every endpoint gets a pytest test in the same PR. No untested routes.
Candidate auth = Google OIDC only, bound to the invited email. Examiner auth = password (argon2) + TOTP. Never mix the two token types.
All queries are org-scoped (multi-tenant from day one). Every table that holds tenant data carries org_id; every repository function takes org_id.
Judge containers: no network, read-only rootfs, non-root user, CPU/memory/pids/time limits. Never weaken these to "make a test pass."
Never commit secrets. Config via env vars, .env is gitignored.
Migrations via Alembic only — never edit schema by hand.
Question versions are immutable. A mid-exam modification creates a NEW version; grading always references the version active at submission time.


Conventions


Async everywhere in backend services; no sync DB calls.
Repository pattern: routers → service layer → repository. Routers stay thin.
Errors: raise domain exceptions, map to HTTP in one exception handler per service.
IDs: UUIDv7 primary keys.
Timestamps: UTC, timezone-aware, named created_at / updated_at.
Frontend: colocate component + test + styles; TanStack Query for server state.


Commands


make dev — start docker-compose (Postgres, Redis, localstack, all services)
make test — run all backend tests
make test SVC=exam — run one service's tests
make lint — ruff + mypy (backend), eslint + tsc (frontend)
make migrate SVC=exam MSG="..." — autogenerate an Alembic migration


Run make test and make lint after every change set, and fix failures
before presenting the diff.

Current phase

Phase 1 MVP — see docs/PHASE1_PROMPTS.md for the slice-by-slice plan:
examiner auth + RBAC, question CRUD, blueprint builder, Gmail invite +
Google SSO, Monaco exam UI, Docker-sandboxed judge (Python/Java/C++),
manual test cases, basic results.

Out of scope for Phase 1 (do not build yet): AI test-case generation,
live follow-ups/WebSocket proctoring, plagiarism detection, analytics,
billing, webcam proctoring.

When unsure

Ask before: adding a new dependency, changing the DB schema of another
service, or altering anything in services/judge/ sandbox limits.
Prefer the boring, well-tested option over the clever one.