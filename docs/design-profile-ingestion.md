# Design note: profile ingestion pipeline (Phase 2, Slice 1)

## Input / output

```
Input:  resume PDF (uploaded straight to S3 via a presigned PUT,
        same pattern as question test-case files) + optional GitHub handle
Output: CandidateProfile {years_exp, domains[], tech_stack[],
        seniority_estimate, weak_signals[], strong_signals[]}
Stored: candidate_profile table, owned by the new `ai` service
```

## New service: `services/ai`

Scaffolded identically to `services/exam` / `services/question`: uv +
pyproject, FastAPI, async SQLAlchemy 2.0 + asyncpg, Alembic, pytest +
pytest-asyncio, `Dockerfile` + `migrate.sh`, its own Postgres database
(`ai`), added to `infra/docker-compose.yml` (`ai-migrate` one-shot +
`ai` app service, mirroring `question-migrate`/`question`).

Like every other service: never imports another service's code; talks
to question/exam only over HTTP; every table carries `org_id`; RS256
**verify-only** (public key), since `ai` never signs tokens — it is called
by the exam/question services and, via the gateway, by the examiner
console directly (for `POST /profiles` from the console after a resume
upload).

## Gateway wiring

`services/gateway/app/routing.py` gets a new `Upstream.AI` and a
`Route("/profiles", Upstream.AI, Policy.EXAMINER)` — examiner-only,
same plane as `/questions`/`/blueprints`. `AI_SERVICE_URL` env var added
next to `EXAM_SERVICE_URL`/`QUESTION_SERVICE_URL`.

## Endpoints

1. `POST /profiles/uploads` — no body. Returns `{resume_s3_key, upload_url}`
   (presigned PUT), exactly like `question`'s test-case upload flow. No DB
   row yet — this is pure S3 presigning.
2. `POST /profiles` — body `{resume_s3_key, github_handle?}`. Creates a
   `candidate_profile` row (`status=queued`), fires the background
   ingestion job, returns `{id, status}` (201).
3. Background job (`asyncio.create_task`, not a new SQS lane — this is a
   single fire-and-forget job per profile, not judge-pipeline work, so it
   doesn't need `judge-live`/`judge-gen`-style queueing; mirrors the shape
   of the existing verdict-consumer background task already running in
   `services/exam`):
   a. Mark `status=processing`.
   b. Fetch the PDF from S3 (direct `boto3 get_object`, server-side —
      unlike the browser-facing presigned PUT above).
   c. Extract text: `pdfplumber` first; if a page yields no extractable
      text (scanned/image PDF), fall back to rendering the page and
      running `pytesseract` OCR on it.
   d. If `github_handle` given: `GitHubClient.fetch_signals(handle)` —
      top languages + repo count/stars via the public GitHub REST API.
   e. `LLMClient.extract_profile(resume_text, github_signals)` →
      structured-output call producing a validated `CandidateProfile`.
   f. Store the result, `status=ready`. Any exception at any step →
      `status=failed`, `error` column set, never raises out of the task.
4. `GET /profiles/{id}` — `{id, status, profile?, error?}`.

## `LLMClient` abstraction (`app/llm/client.py`)

Single internal module every LLM call goes through (per the Phase 2
standing instructions — never call the Anthropic API directly from a
router or service). Shape mirrors the existing `EmailSender` protocol:

```python
class LLMClient(Protocol):
    async def extract_profile(self, resume_text: str, github_signals: GitHubSignals | None) -> CandidateProfile: ...

class MockLLMClient:      # default backend; deterministic, no network, no key needed
class AnthropicLLMClient: # real Claude calls with structured output, retry + cost logging
```

Selected via `settings.llm_backend` (`"mock" | "anthropic"`, default
`"mock"`), same pattern as `EMAIL_BACKEND`. `validate_production_config`
requires `ANTHROPIC_API_KEY` set when `env == "production"` and
`llm_backend == "anthropic"` — fails fast on startup, never silently
falls back. Per this session's decision, real keys aren't being wired up
yet: dev/CI run entirely on `MockLLMClient`, so no cost is incurred and no
key is required to develop or test this slice. Retry logic (bounded
retries with backoff on transient API errors) and a per-call structured
log line (model, input/output tokens, latency) live only in
`AnthropicLLMClient` — `MockLLMClient` needs neither.

## `GitHubClient` abstraction (`app/clients/github.py`)

Same shape: `Protocol` + `MockGitHubClient` (default, deterministic
fixture signals) + `RealGitHubClient` (unauthenticated public REST API
calls — no token required for public repo/language data, so no secret
to manage; still mocked in tests for determinism and to avoid live
network calls in CI).

## `candidate_profile` table

```
id                uuid7 pk
org_id            uuid, indexed        -- multi-tenant, per Hard Rule 4
status            enum: queued | processing | ready | failed
resume_s3_key      text
github_handle      text, nullable
years_exp          int, nullable       -- populated once status=ready
domains            text[], nullable
tech_stack         text[], nullable
seniority_estimate text, nullable
weak_signals       text[], nullable
strong_signals     text[], nullable
error              text, nullable      -- populated once status=failed
created_at         timestamptz
updated_at         timestamptz
```

No FK to any exam-service table — `exam` will hold `profile_id` as a
plain UUID value when Slice 4 (Mode 2 scheduling) wires them together,
consistent with "services never import each other's code" (no cross-service
DB FKs either).

## Tests

- Fixture PDF (small, checked-in text-based PDF) → `pdfplumber` extraction
  test; a second fixture with no extractable text → OCR fallback path
  exercised with a fake/monkeypatched `pytesseract`.
- `MockLLMClient` and `MockGitHubClient` injected via FastAPI dependency
  overrides (same mechanism the existing `EmailSender` tests use) — no
  real network calls in the suite.
- Job lifecycle: queued → processing → ready (happy path) and → failed
  (each of PDF-extraction, GitHub-fetch, and LLM-call raising is a
  separate test case).
- `GET /profiles/{id}` for an unknown id → 404; for another org's id →
  404 (org-scoped, never 403 — don't leak existence across tenants).

## Non-goals for this slice

Question generation, test-case factory, Mode 2 scheduling, adaptive
difficulty, live proctoring, evaluation, and hiring reports are Slices
2–8 and out of scope here. This slice only stands up `services/ai` and
gets a validated `CandidateProfile` stored from a resume + optional
GitHub handle.
