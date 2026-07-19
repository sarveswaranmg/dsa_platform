DSA Exam Platform — Architecture Reference

This is the system of record for design intent. If code and this document
disagree, flag it — don't silently pick one. Phase scoping lives in
CLAUDE.md and docs/PHASE1_PROMPTS.md; this document describes the full
target system, including Phase 2+ pieces, so that Phase 1 code leaves the
right seams.

1. Product summary

An invite-only, adaptive DSA assessment platform with three differentiators:


Blueprint engine — examiners compose exams from a candidate profile
(role, experience band) as a weighted topic mix with a difficulty curve.
Blueprints are versioned templates, reusable across hiring drives.
AI test-case factory — LLM-generated edge/adversarial/stress cases,
accepted only after differential validation (reference solution and
brute-force solution must agree on every case). Raw LLM output is never
trusted as ground truth.
Live follow-up channel — a proctor can modify constraints or push a
follow-up question mid-exam over WebSocket. Every modification creates a
new immutable question version; grading binds to the version active at
submission time.


Two user planes, never mixed:


Examiners log in (argon2 password + TOTP; org SSO later) with RBAC
roles: admin (org + examiner management), author (questions,
blueprints), proctor (live monitoring, follow-up pushes), reviewer
(grading, reports).
Candidates never register. They receive a single-use, time-boxed,
signed invite link bound to a specific Gmail address, authenticate via
Google OIDC, and the platform verifies the authenticated email exactly
matches the invited email. Success consumes the token and issues an
exam-scoped JWT valid only for that session window.


2. Topology

Examiner console (React)      Candidate exam UI (React + Monaco)
            \                          /            (WebSocket for verdicts,
             \                        /              timers, follow-ups)
              +----- API gateway ----+
              |  TLS, JWT validation (two token types),
              |  rate limiting, CORS, request-id propagation
              +----+----------+-----------+
                   |          |           |
             Exam service  Question   Judge queue (SQS)
             (blueprints,  service        |
              sessions,   (bank, AI   Judge workers
              invites,     test-case  (sandboxed exec,
              WS hub)      factory)    autoscaled)
                   \          |           /
              Postgres      Redis       S3/MinIO
              (record)   (sessions,   (code, test-case
                          presence,    files, replays)
                          rate limits)

Supporting services: notification (SES/SendGrid behind an interface;
console/SMTP stub in dev), analytics (reports, cohort comparisons,
question-quality metrics), plus observability (structured JSON logs with
request ids, Prometheus/CloudWatch metrics, OpenTelemetry traces, Sentry).

Service boundaries are hard: no cross-service code imports; HTTP or queue
only. Every service is stateless — all session state lives in Redis so any
pod serves any request.

3. Services

3.1 Gateway

Terminates TLS, validates JWTs at the edge, distinguishes examiner tokens
from candidate exam-scoped tokens (different signing keys or aud claims;
a candidate token must never reach an examiner route and vice versa),
applies per-identity Redis rate limits, handles CORS, and propagates a
request id to all downstream calls.

3.2 Exam service

Owns: orgs and examiners (auth, RBAC), blueprints, exam scheduling,
invites, candidate sessions, results, and the WebSocket hub.


Blueprints: versioned templates — target role, experience band, total
duration, topic mix as [{topic_id, weight, difficulty_range, question_count}], weights sum to 100. Concretization samples questions
from the question service over HTTP with per-candidate deterministic
seeding: equivalent but non-identical sets (anti-cheat by construction).
Invites: single-use signed token (stored jti in Redis for revocation
and single-use enforcement), bound to email + exam + time window.
Rejection paths: reuse, expiry, email mismatch, tampering.
Sessions: server-authoritative timer in Redis; start only inside the
window; auto-submit and lock on expiry; resumable after disconnect;
every submission stores the question version id it answered.
WebSocket hub: verdict push, server-clock sync, and (Phase 2)
follow-up delivery and proctor live views. Presence in Redis pub/sub so
the hub scales horizontally.


3.3 Question service

Owns: topic taxonomy (self-referencing tree, e.g. arrays → two pointers →
sliding window), questions, versions, test cases, and the AI factory.


Questions: title, statement (markdown), constraints, difficulty 1–5,
topics (m2m), time/memory limits per language, starter code per language.
Versions are immutable. Editing a published question, or a proctor
modifying it mid-exam, creates a new version. Nothing ever rewrites a
version a candidate may have answered.
Test cases: metadata rows in Postgres pointing at S3 objects (large
stress inputs never live in the DB). Presigned URLs for upload/download.
Difficulty calibration (Phase 3): ratings self-adjust from observed
pass rates and discrimination index, not just author judgment.


AI test-case factory (Phase 2) — background jobs, never inline in a
request:


LLM drafts candidate cases (edge, adversarial, stress) given the
statement and constraints.
Constraint validator checks each input against declared bounds.
Differential testing: run the examiner-approved reference solution AND a
brute-force solution on every case; keep only cases where outputs agree.
Disagreement = discard the case and log it (it may indicate a buggy
reference — surface to the author).
Examiner approves the final set before it can appear in an exam.


The factory can also generate a validated case set on demand in seconds for
a freshly pushed mid-exam follow-up, against a reference solution the
proctor supplies or approves. LLM calls go through one internal generation
module with caching, retries, and per-org token-cost tracking.

3.4 Judge service

The component that must never fall over and must never be weakened.


Pipeline: exam service publishes a submission job → SQS → worker
pulls, fetches test cases from S3, compiles/runs, compares output (exact
and whitespace-tolerant modes) per case → publishes verdict message →
exam service persists and pushes over WebSocket. Jobs are idempotent
(dedupe on submission id).
Sandbox (hard rules, restated from CLAUDE.md): per-run container with
no network, read-only rootfs + tmpfs scratch, non-root uid, CPU/wall-time
limit, memory limit, pids limit, output-size cap. Per-language runner
images (Python 3.12, Java 21, C++ g++ 13; more later). Docker + gVisor as
the target runtime; Firecracker microVMs are the long-term option.
Verdicts: AC / WA / TLE / MLE / RE / CE per test case, with runtime
and peak memory.
Scaling: workers autoscale on queue depth. A submission spike means
temporary latency, never failure. The queue is the shock absorber.
A standing security test suite asserts that fork bombs, rootfs writes,
network egress, env/host reads, and stdout floods all fail.


3.5 Notification and analytics

Notification: invite emails, reminders, results. One provider interface;
SES in prod, console/SMTP stub in dev. Analytics (Phase 3): per-candidate
reports, cohort comparisons, per-question pass rates and discrimination
index, examiner dashboards.

4. Live follow-up model (Phase 2, but shapes Phase 1 schema)

Every question within a session is an event-sourced stream:

question_assigned → code_snapshot* → submission → verdict
                 ↘ constraint_modified / followup_pushed  (creates new
                    question version; UI shows a requirements diff banner)

Events are append-only rows (session_id, seq, type, payload, question_ version_id, created_at). Benefits: perfect session replay for review and
dispute resolution, and unambiguous grading (each submission references the
version that was active). Phase 1 must therefore already store
question_version_id on submissions and keep versions immutable — the
event table itself can arrive in Phase 2.

Anti-cheat framing: per-candidate seeded variants plus real-time follow-ups
are the primary defense against candidates outsourcing to an external LLM —
a live constraint change is hard to relay in real time. Additional layers:
copy-paste and tab-switch telemetry, MOSS-style token-fingerprint code
similarity across candidates (Phase 3), optional webcam proctoring
(premium, later).

5. Data layer


Postgres 16 — system of record: orgs, examiners, candidates,
questions, versions, test-case metadata, blueprints, exams, invites,
sessions, submissions, verdicts, events. Every tenant table carries
org_id; every repository function takes org_id (multi-tenancy is
structural). UUIDv7 keys; UTC timestamps.
Redis — invite jti store, session state and timers, WebSocket
presence/pub-sub, rate limits, hot aggregates.
S3/MinIO — submitted code, test-case files, session replays.
OpenSearch (Phase 3) — full-text question search.


Core relationships:

org 1—n examiner
org 1—n question 1—n question_version 1—n test_case(→S3)
question n—m topic (tree)
org 1—n blueprint(versioned) 1—n exam 1—n invite(email-bound)
exam 1—n session 1—n submission(→question_version) 1—n case_verdict
session 1—n event   (Phase 2)

6. Security model


Two token planes (examiner vs candidate) with distinct lifetimes, claims,
and audiences; validated at the gateway and re-checked in services.
Invite tokens: single-use, time-boxed, signed, email-bound; consumed
atomically on first successful OIDC match.
RBAC enforced via a require_role(...) dependency; cross-org access is a
tested rejection path everywhere.
Sandbox rules per §3.4; never relaxed to make a test pass.
Secrets via env vars only; .env gitignored; no secrets in logs.
Rate limiting per identity at the gateway; request-id in every log line.


7. Scalability posture

Stateless services behind the gateway (horizontal scale), Redis-backed
session state, queue-buffered judging with autoscaled workers, S3 for all
large blobs, CDN for frontend assets. Target: thousands of concurrent
candidates with the judge queue absorbing submission bursts. Postgres
scales up first, read replicas later; org-scoped schema keeps a future
shard-by-org option open.

8. Phasing


Phase 1 (MVP): examiner auth + RBAC, question CRUD + taxonomy +
manual test cases, blueprint builder with seeded sampling, invite +
Google OIDC, session lifecycle, Docker-sandboxed judge (Py/Java/C++),
candidate exam UI (Monaco), examiner console, gateway, e2e proof.
Phase 2: AI test-case factory with differential validation, WebSocket
live proctoring, mid-exam follow-ups (event sourcing), session replay.
Phase 3: adaptive difficulty within an exam, plagiarism detection,
analytics dashboards, difficulty self-calibration, OpenSearch, billing,
optional webcam proctoring.


Each Phase 2+ feature gets a short design note in docs/ before any
implementation prompt.