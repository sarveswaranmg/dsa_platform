# DSA Exam Platform

Adaptive, invite-only DSA assessment platform. Examiners compose exams from a
candidate's role/experience profile, AI generates validated test cases, and
examiners can push live follow-ups mid-exam over WebSocket.

**Read `docs/architecture.md` before any non-trivial task.**

## Stack

- **Backend**: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic
- **Data**: Postgres 16 (system of record), Redis (sessions, presence, rate limits), S3/MinIO (submissions, large test-case files)
- **Queue**: SQS-compatible (localstack in dev) for the judge pipeline
- **Frontend**: React 18 + TypeScript + Vite, Monaco editor, native WebSocket
- **Infra**: Docker Compose for dev. Terraform for prod (VPC, RDS, ElastiCache,
  S3, SQS, ECS, judge node pool) is planned but not yet written — see the
  Production readiness section below. Do not assume Terraform files exist
  until this line is updated.
- **Tests**: pytest + pytest-asyncio (backend), Vitest + React Testing Library (frontend)

## Repo layout


services/gateway/    # routing, JWT validation, rate limiting
services/exam/       # blueprints, sessions, invites, WebSocket hub
services/question/   # question bank, taxonomy, AI test-case factory
services/judge/      # queue consumer + sandboxed execution workers
frontend/            # examiner console + candidate exam UI
infra/               # docker-compose, Terraform, localstack config
docs/                # architecture.md, DECISIONS.md, design notes

## Hard rules

1. Services NEVER import each other's code. Communication is HTTP or queue only.
2. Every endpoint gets a pytest test in the same PR. No untested routes.
3. Candidate auth = Google OIDC only, bound to the invited email. Examiner auth = password (argon2) + TOTP. Never mix the two token types.
4. All queries are org-scoped (multi-tenant from day one). Every table that holds tenant data carries `org_id`; every repository function takes `org_id`.
5. Judge containers: no network, read-only rootfs, non-root user, CPU/memory/pids/time limits. Never weaken these to "make a test pass."
6. Never commit secrets. Config via env vars, `.env` is gitignored.
7. Migrations via Alembic only — never edit schema by hand.
8. Question versions are immutable. A mid-exam modification creates a NEW version; grading always references the version active at submission time.

## Conventions

- Async everywhere in backend services; no sync DB calls.
- Repository pattern: routers → service layer → repository. Routers stay thin.
- Errors: raise domain exceptions, map to HTTP in one exception handler per service.
- IDs: UUIDv7 primary keys.
- Timestamps: UTC, timezone-aware, named `created_at` / `updated_at`.
- Frontend: colocate component + test + styles; TanStack Query for server state.

## Commands

- `make dev` — start docker-compose (Postgres, Redis, localstack, all services)
- `make test` — run all backend tests
- `make test SVC=exam` — run one service's tests
- `make lint` — ruff + mypy (backend), eslint + tsc (frontend)
- `make migrate SVC=exam MSG="..."` — autogenerate an Alembic migration
- `make migrate-run` — apply pending migrations via each service's one-shot
  migrate container (exam, question); `make dev` also runs this
  automatically before the app containers start
- `make build-frontend` — build the production frontend image (`npm run
  build`, served via nginx); override the gateway origin with
  `VITE_API_BASE_URL=...`

Run `make test` and `make lint` after every change set, and fix failures
before presenting the diff.

## Current phase

**Phase 1 MVP: complete.** Examiner auth + RBAC, question CRUD, blueprint
builder, Gmail invite + Google SSO, Monaco exam UI, Docker-sandboxed judge
(Python/Java/C++), manual test cases, basic results, e2e proof — all built
and verified (186 tests passing). See `docs/PHASE1_PROMPTS.md` for the
slice history.

**Now in progress: production readiness** (see checklist below), then
Phase 2 (AI test-case generation, live follow-ups/WebSocket proctoring —
scoped in `docs/architecture.md`). Do not start Phase 2 slices until the
readiness checklist is cleared.

## Production readiness (not yet done)

- [ ] CI: GitHub Actions running `make lint` + `make test` on push/PR
- [ ] Split `alembic upgrade head` out of app start command → one-shot migration task
- [ ] Redis: replace numeric DB indexes (gateway=1, exam=0) with key prefixes
      (ElastiCache cluster mode doesn't support multiple logical DBs)
- [ ] RS256 token split: exam signs with private key; gateway/question verify
      with public key only (currently shared HS256 secret — gateway can mint
      tokens, which it shouldn't be able to do)
- [ ] Judge isolation: dedicated node pool (MVP) → gVisor (`--runtime=runsc`)
      → Firecracker (stretch). Never co-tenant judge workers with other services.
- [ ] Frontend: `npm run build` → S3/CloudFront (Vite dev server is dev-only).
      A Docker/nginx build already exists (`frontend/Dockerfile`, `make
      build-frontend`, `infra/docker-compose.prod.yml`) as an interim/local
      "prod-like" option — nginx proxies API paths same-origin, so
      `VITE_API_BASE_URL` is a Docker build-arg baked into nginx's config,
      not into the JS bundle. `VITE_API_BASE_URL` must be set at build time
      in CI/CD (per environment) for either path; the eventual direct
      S3/CloudFront static hosting has no proxy layer, so that path will
      need `VITE_API_BASE_URL` baked into the JS bundle instead (not yet
      wired — `frontend/src` makes only same-origin relative fetches today).
- [ ] SES implementation behind existing `EmailSender` protocol
- [ ] Real Google OIDC client + authorized redirect URIs for the real domain
- [ ] TLS terminated at the load balancer (everything is plain HTTP today)
- [ ] Terraform: VPC, RDS, ElastiCache, S3+CORS, SQS, ECS services, judge ASG
- [ ] Move S3 bucket + CORS policy out of app bootstrap (gated to `env == "dev"`)
      into Terraform

## When unsure

Ask before: adding a new dependency, changing the DB schema of another
service, or altering anything in `services/judge/` sandbox limits.
Prefer the boring, well-tested option over the clever one.