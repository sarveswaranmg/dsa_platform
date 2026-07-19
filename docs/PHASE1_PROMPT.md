Phase 1 build plan — Claude Code prompt sequence

How to use this file: one slice = one Claude Code session. Start every slice
in Plan mode, review/edit the plan, then let it execute. Commit after each
accepted slice (git commit messages are given). Check the box, record any
decision worth defending in an interview in docs/DECISIONS.md, move on.
If a session gets long and sluggish, start a fresh conversation — CLAUDE.md
carries the context.


Slice 0 — Repo skeleton and dev environment


 Prompt:

Set up the monorepo per CLAUDE.md's repo layout. Create services/exam
as the reference FastAPI service: app factory, async SQLAlchemy 2.0
session management, Alembic wired up, /healthz endpoint, pytest with an
async test client and a test-database fixture. Add docker-compose with
Postgres 16, Redis, and localstack, plus the Makefile targets from
CLAUDE.md (dev, test, lint, migrate). Plan first.




 Verify: make dev boots, make test passes, /healthz returns 200.
 Commit: chore: monorepo skeleton, exam service scaffold, dev env


Slice 1 — Examiner auth + RBAC


 Prompt:

In services/exam, implement examiner authentication: registration and
login with argon2 password hashing, TOTP enrollment and verification
(pyotp), short-lived access JWT + refresh token rotation. JWT carries
org_id and role (admin | author | proctor | reviewer). Add a FastAPI
dependency require_role(...) enforcing RBAC, and an org model so every
examiner belongs to an org. Tests for: happy paths, wrong password, bad
TOTP, expired token, role denial, cross-org access denial. Plan first.




 Verify: run tests; manually walk the register → TOTP → login flow with curl.
 Commit: feat(exam): examiner auth with TOTP and RBAC


Slice 2 — Question service: CRUD + taxonomy


 Prompt:

Create services/question copying the patterns from services/exam
(app factory, DB setup, test fixtures). Implement: topic taxonomy as a
self-referencing table (e.g. arrays → two-pointers → sliding-window),
question CRUD (title, statement markdown, constraints, difficulty 1–5,
topics m2m, time/memory limits, starter code per language), and
immutable question versions — editing a published question creates a new
version. Test cases are metadata rows pointing at S3 keys (use MinIO/
localstack in dev); include upload/download presigned-URL endpoints.
Author role required for writes. Tests included. Plan first.




 Commit: feat(question): question bank with taxonomy and immutable versions


Slice 3 — Blueprint builder


 Prompt:

In services/exam, implement exam blueprints: a versioned template with
target role, experience band, total duration, and a topic mix (list of
{topic_id, weight, difficulty_range, question_count}). Add an endpoint
that, given a blueprint, samples a concrete question set from the
question service over HTTP (no code imports) with deterministic seeding
per candidate so each candidate gets an equivalent but non-identical set.
Validate weights sum to 100. Tests: sampling determinism, insufficient
question pool, cross-org isolation. Plan first.




 Commit: feat(exam): versioned blueprints with seeded question sampling


Slice 4 — Invite flow + Google SSO for candidates


 Prompt:

Implement the candidate invite flow in services/exam:


Examiner schedules an exam for a candidate email + blueprint + time
window; system generates a single-use signed invite token (itsdangerous
or JWT jti stored in Redis) and emails the link (console/SMTP stub in
dev, SES-ready interface).
Candidate opens the link → Google OIDC (authlib) → verify the
authenticated email EXACTLY matches the invited email → consume the
token → issue an exam-scoped JWT valid only for that session window.
Reject: reused token, expired window, email mismatch, tampered token.
Tests for every rejection path. Plan first — I want to review the token
design before you write code.





 Record in DECISIONS.md: invite token format, why email-binding check
happens server-side after OIDC, token TTL choices.
 Commit: feat(exam): single-use invites with Google OIDC email binding


Slice 5 — Judge service (the crown jewel — take 2–3 sessions)


 Session A prompt (design + runner):

Create services/judge. Plan mode first, and stop after the plan.
Design a worker that consumes submission jobs from SQS (localstack),
and executes untrusted code in a Docker container with: no network,
read-only rootfs + tmpfs scratch dir, non-root uid, CPU/wall-time limit,
memory limit, pids limit, output-size cap. Support Python 3.12, Java 21,
C++ (g++ 13) via per-language runner images. Per test case, return
verdict AC/WA/TLE/MLE/RE/CE with runtime and memory used.




 Session B prompt (pipeline):

Implement the full pipeline: exam service publishes a submission job →
judge pulls, fetches test cases from S3, runs each case, compares output
(exact + whitespace-tolerant modes) → publishes a verdict message →
exam service persists results. Idempotent job handling (dedupe on
submission id). Integration test that runs a real container end-to-end
for a correct solution, a wrong one, an infinite loop (TLE), and a
memory bomb (MLE).




 Session C prompt (hardening):

Attempt to break the sandbox and fix what you find: fork bombs, writing
to rootfs, network egress attempts, reading env vars/host paths, huge
stdout. Add a security test suite that asserts each attack fails.




 Personally read every line of the sandbox config. This is the piece
interviews will drill into.
 Commit per session: feat(judge): sandboxed runner, feat(judge):     queue pipeline with verdicts, test(judge): sandbox escape suite


Slice 6 — Exam session lifecycle


 Prompt:

In services/exam, implement the candidate exam session: start (within
window only), fetch assigned questions one at a time, server-side timer
with Redis-backed state so any pod can serve any candidate, submit code
(enqueue to judge), poll/receive verdicts, auto-submit and lock on
expiry. Store every submission with its question version id. Tests:
timer expiry, submitting after lock, resuming after disconnect. Plan
first.




 Commit: feat(exam): stateless exam session lifecycle


Slice 7 — Frontend: candidate exam UI


 Prompt:

In frontend/, build the candidate flow: invite link → Google sign-in →
exam room. Exam room: question statement panel (markdown), Monaco editor
with language selector and starter code, run/submit buttons, verdict
panel per test case, countdown synced to the server clock, and a
requirements-changed banner component (unused in Phase 1, wired for
Phase 2). TanStack Query for API state. Component tests for the verdict
panel and timer. Plan first.




 Commit: feat(frontend): candidate exam room with Monaco


Slice 8 — Frontend: examiner console


 Prompt:

Build the examiner console: login with TOTP, question bank browser with
taxonomy filters, question editor with markdown preview and test-case
upload, blueprint builder form (topic mix with weights and a live
validation that weights sum to 100), exam scheduling with candidate
email invites, and a results page listing candidates with per-question
verdicts and submitted code (read-only Monaco). Role-gate routes to
match backend RBAC. Plan first.




 Commit: feat(frontend): examiner console


Slice 9 — Gateway + polish


 Prompt:

Implement services/gateway: route table to exam/question services,
JWT validation at the edge (examiner vs candidate token types), Redis
rate limiting per identity, CORS, and request-id propagation. Add
structured JSON logging with request ids across all services. Update
docker-compose so the frontend talks only to the gateway. Plan first.




 Commit: feat(gateway): edge routing, auth validation, rate limits


Slice 10 — End-to-end proof + README


 Prompt:

Write an end-to-end test script that exercises the whole MVP: create
examiner → author a question with test cases → build a blueprint →
invite candidate → candidate authenticates → submits a correct and an
incorrect solution → examiner sees verdicts. Then write a README with
architecture overview, a diagram, setup instructions, and a demo GIF
placeholder.




 Record a 2–3 minute demo video. Pin the repo on GitHub.
 Commit: test: full MVP e2e; docs: README



Standing instructions (apply to every slice)


Plan mode first; edit the plan before approving.
After implementation: make test && make lint, fix failures, then show diffs.
Small commits; never bundle two slices.
Anything touching services/judge limits or auth token logic: explain the
change in plain English before applying.
You (the human) write DECISIONS.md entries — Claude builds it, you must be
able to defend it.


Phase 2 preview (do not start until Phase 1 e2e passes)

AI test-case factory with differential validation → WebSocket live
proctoring → mid-exam follow-up pushes (event-sourced question versions) →
session replay. Write a design note in docs/ for each before prompting.