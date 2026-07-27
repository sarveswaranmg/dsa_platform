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
  S3, SQS, ECS, judge node pool) is written under `infra/terraform/` — see the
  Production readiness section below for the two items still open.
- **Tests**: pytest + pytest-asyncio (backend), Vitest + React Testing Library (frontend)

## Repo layout


services/gateway/    # routing, JWT validation, rate limiting
services/exam/       # blueprints, sessions, invites, WebSocket hub
services/question/   # question bank, taxonomy, AI test-case factory
services/judge/      # queue consumer + sandboxed execution workers
services/ai/         # candidate profile ingestion, question/test-case
                     # generation, adaptive difficulty, evaluation (Phase 2)
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

**Production readiness: substantially done** (see checklist below — 2 items
open). **Now starting Phase 2** (AI test-case generation, live
follow-ups/WebSocket proctoring — scoped in `docs/architecture.md`,
slice plan in `docs/PHASE2_PROMPTS.md`). Work through Phase 2 one slice per
session: write the slice's `docs/design-*.md` note, Plan mode, implement,
`make test && make lint`, commit, get sign-off before starting the next slice.

## Production readiness

- [x] CI: GitHub Actions running `make lint` + `make test` on push/PR
      (`.github/workflows/ci.yml`)
- [x] Split `alembic upgrade head` out of app start command → one-shot
      migration task (`exam-migrate`/`question-migrate` in
      `infra/docker-compose.yml`; ECS one-shot task via
      `scripts/run-migrate-task.sh` + `.github/workflows/deploy.yml`)
- [x] Redis: numeric DB indexes replaced with key prefixes
      (`services/exam/app/core/redis_keys.py` — `ex:` prefix; single
      logical DB, ElastiCache cluster-mode compatible)
- [x] RS256 token split: exam signs with the private key only; gateway and
      question only hold the public key and verify
      (`services/exam/app/core/security.py`,
      `services/gateway/app/auth.py`, `services/question/app/core/security.py`)
- [ ] **Judge isolation** — dedicated node pool done
      (`infra/terraform/modules/judge-asg`); gVisor (`--runtime=runsc`) is
      wired and supported but `terraform.tfvars.example` still defaults
      `judge_runtime = "runc"`. Firecracker not started. Never co-tenant
      judge workers with other services.
- [x] Frontend: `npm run build` → S3/CloudFront via
      `.github/workflows/deploy.yml` (`deploy-frontend` job) +
      `infra/terraform/modules/frontend-cdn`. The Docker/nginx build
      (`frontend/Dockerfile`, `make build-frontend`,
      `infra/docker-compose.prod.yml`) remains as an interim/local
      "prod-like" option.
- [x] SES implementation behind the `EmailSender` protocol
      (`services/exam/app/notifications/ses_sender.py`)
- [ ] **Real Google OIDC client** — infra wires real secrets end-to-end
      (`infra/terraform/modules/secrets`), but registering the actual OAuth
      client + authorized redirect URIs in Google Cloud Console for the
      real domain is an external, non-code step that still needs doing.
- [x] TLS terminated at the load balancer
      (`infra/terraform/modules/alb` — ACM cert + HTTPS:443 listener,
      HTTP→HTTPS redirect)
- [x] Terraform: VPC, RDS, ElastiCache, S3+CORS, SQS, ECS services, judge
      ASG (`infra/terraform/modules/*`, wired in `infra/terraform/envs/prod/main.tf`)
- [x] S3 bucket + CORS policy moved out of app bootstrap into Terraform
      (`services/question/app/main.py` only calls `ensure_bucket()` when
      `env == "dev"`; prod bucket/CORS is `infra/terraform/modules/s3-app`)

## When unsure

Ask before: adding a new dependency, changing the DB schema of another
service, or altering anything in `services/judge/` sandbox limits.
Prefer the boring, well-tested option over the clever one.