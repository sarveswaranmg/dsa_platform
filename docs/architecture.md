# DSA Exam Platform — Architecture Reference

This is the system of record for design intent. If code and this document
disagree, flag it — don't silently pick one. Phase scoping lives in
`CLAUDE.md`; this document describes the full target system so Phase 1/2
code leaves the right seams for Phase 3.

---

## 1. Product summary

An AI-powered, invite-only DSA assessment platform with two exam modes and
three core differentiators.

### Two exam modes

**Mode 1 — Examiner-directed**
Examiner specifies: topic mix, difficulty band, time limit, candidate email.
AI generates questions and test cases to exactly those specs.
Examiner optionally reviews before the invite goes out.

**Mode 2 — Profile-driven**
Examiner specifies: candidate email + target role/seniority (e.g. "SDE-2,
backend"). AI reads the candidate's resume/GitHub profile, infers the
appropriate topic mix and difficulty, generates questions and test cases
automatically. Examiner optionally reviews before the invite goes out.

Both modes share the same judge pipeline, session lifecycle, invite/auth
flow, and WebSocket layer. The only difference is who drives the question
spec — the examiner explicitly, or the AI from the candidate profile.

### Three differentiators

1. **Dual-mode composition** — examiner control when you want it, full AI
   automation when you don't. Adapts to the hiring team's workflow.
2. **Validated AI generation** — questions and test cases are generated and
   validated automatically (differential testing; no human approver
   required), but examiners can always review and override.
3. **AI hiring signal** — beyond AC/WA verdicts: approach recognition,
   complexity analysis, partial credit, behavioural signals, and a
   structured seniority-calibrated report.

---

## 2. User planes

**Examiners** (argon2 + TOTP; org SSO later) with RBAC roles:
- `admin` — org and examiner management
- `author` — question bank, blueprints (Mode 1 only)
- `proctor` — live monitoring, follow-up pushes
- `reviewer` — grading, reports

**Candidates** never register. Single-use, time-boxed, signed invite link
bound to a specific Gmail address → Google OIDC → email-binding check →
exam-scoped JWT. No match, no entry. Token consumed atomically on first
successful auth.

---

## 3. Topology

```
Examiner console (React)        Candidate exam UI (React + Monaco)
        \                                /
         \                              /   WebSocket: verdicts,
          +-------- API gateway -------+    timers, follow-ups
          |  TLS · JWT validation (two token types)
          |  rate limiting · CORS · request-id propagation
          +------+----------+----------+-----------+
                 |          |          |           |
           Exam service  Question   AI service  Judge queue
           (blueprints,  service    (profile    (SQS)
            sessions,   (bank,      ingestion,      |
            invites,     versioned  generation,  Judge workers
            WS hub)      questions) evaluation)  (sandboxed,
                 \          |          |          autoscaled)
                  \         |          |         /
               Postgres   Redis      S3/MinIO
               (record)  (sessions,  (resumes, code,
                          presence,   test-case files,
                          rate limits) session replays)
```

Services communicate via HTTP or SQS only — no cross-service code imports.
Every service is stateless; all session state lives in Redis.

---

## 4. Services

### 4.1 Gateway
TLS termination, JWT validation (examiner vs candidate tokens — distinct
signing keys, distinct `aud` claims), per-identity Redis rate limits, CORS,
request-id propagation. A candidate token must never reach an examiner route.

### 4.2 Exam service
Owns: orgs, examiners (auth, RBAC), blueprints, exam scheduling, invites,
candidate sessions, results, WebSocket hub.

**Blueprints (Mode 1):** versioned templates — role, experience band,
duration, topic mix `[{topic_id, weight, difficulty_range, count}]`,
weights sum to 100. Concretization calls AI service to generate questions
to spec, seeded per candidate (equivalent but non-identical sets).

**Profile-driven scheduling (Mode 2):** examiner provides candidate email
+ target role/seniority. Exam service calls AI service with the candidate
profile; AI service returns a question spec (topic mix + difficulty band);
exam service uses it as an auto-generated blueprint. Examiner can review
and override before the invite goes out.

**Invites:** single-use signed token (jti in Redis), bound to email + exam
+ time window. Rejection paths: reuse, expiry, email mismatch, tampering.

**Sessions:** server-authoritative timer in Redis; start only inside window;
auto-submit and lock on expiry; resumable after disconnect; every submission
stores the question **version id** it answered.

**WebSocket hub:** verdict push, server-clock sync, follow-up delivery
(Phase 2), proctor live views. Presence via Redis pub/sub.

### 4.3 Question service
Owns: topic taxonomy (self-referencing tree), questions, immutable versions,
test cases.

**Questions:** title, statement (markdown), constraints, difficulty 1–5,
topics (m2m), time/memory limits per language, starter code per language.

**Versions are immutable.** Editing a published question or a proctor
modifying one mid-exam creates a new version. Grading always binds to the
version active at submission time.

**Test cases:** metadata rows in Postgres pointing at S3 objects. Presigned
URLs for upload/download. Never store large inputs in the DB.

**Difficulty calibration (Phase 3):** ratings self-adjust from observed pass
rates and discrimination index.

### 4.4 AI service (new — Phase 2)
The intelligence layer. Stateless FastAPI service; calls LLM APIs (Anthropic
Claude / OpenAI) behind an internal abstraction with caching, retries, and
per-org token-cost tracking.

#### 4.4.1 Profile ingestion
Input: resume PDF + optional GitHub handle.
Pipeline:
1. Extract text from PDF (pdfplumber / Tesseract for scanned docs).
2. Parse GitHub: top languages, repo complexity signals, contribution
   patterns via GitHub API.
3. LLM call: structured extraction → `CandidateProfile` Pydantic model:
   `{years_exp, domains[], tech_stack[], seniority_estimate, weak_signals[],
   strong_signals[]}`.
4. Profile vector stored in Postgres, referenced by the exam session.

#### 4.4.2 Question generation
Input: topic + difficulty band + constraints (from blueprint or profile).
Pipeline:
1. LLM generates: problem statement, input/output format, constraints,
   2–3 worked examples, starter code per language.
2. **Reference solution generation:** strong model generates an optimal
   solution with complexity annotation.
3. **Brute-force generation:** weaker/different model generates a naive
   solution independently.
4. **Automated validation:**
   - Static analysis: constraints well-formed, examples consistent.
   - Generate 50–100 random inputs within constraints.
   - Run reference and brute-force against all inputs via judge pipeline.
   - If agreement rate < 95% → discard, regenerate (up to 3 attempts).
   - Agreement rate ≥ 95% → question accepted.
5. Question + reference + brute-force stored as a new version in question
   service. Examiner can review and override; exam proceeds either way.

#### 4.4.3 Test case factory
Input: accepted question version + reference solution + brute-force solution.
Pipeline:
1. LLM generates candidate cases: edge cases, adversarial inputs, stress
   inputs (large n, all-same elements, sorted/reverse-sorted, etc.).
2. Constraint validator: each input checked against declared bounds.
3. Differential testing: run reference + brute-force on every case via
   judge pipeline; keep only cases where both agree. Disagreements discarded
   and logged.
4. Test cases stored against the question version in S3.

For mid-exam proctor follow-ups: factory runs on demand in seconds for the
new constraint, attached to the new question version.

#### 4.4.4 Adaptive difficulty engine
Watches the candidate session in real time:
- Solved in < 30% of allotted time, optimal complexity → raise difficulty
- Past 60% of time, no AC → hold or lower
- Simplified IRT model; calibrates from real session data in Phase 3.
Signals sent to exam service which adjusts next question selection.

#### 4.4.5 AI evaluation
Runs after session ends (async, does not block result delivery):
1. **Complexity analysis:** static AST analysis + LLM annotation —
   detected time/space complexity vs optimal.
2. **Approach recognition:** which algorithm family? Correct approach with
   implementation bug vs fundamentally wrong approach.
3. **Partial credit scoring:** 0.0–1.0 per question beyond binary AC/WA.
4. **Behavioural signals:** run count before AC, response to TLE/WA,
   manual edge case testing detected from run history.
5. All signals written to `session_evaluation` table.

#### 4.4.6 Hiring signal report
Input: completed session + evaluation signals.
Output: structured `HiringReport`:
```json
{
  "seniority_match": "SDE-2",
  "strong_areas": ["graphs", "heaps"],
  "weak_areas": ["DP"],
  "code_quality": "production-grade",
  "problem_solving": "optimal approach, implementation errors",
  "overall_score": 0.78,
  "recommendation": "proceed",
  "evidence": [
    {"question": "...", "verdict": "AC", "approach": "BFS", "complexity": "O(V+E)", "partial_score": 1.0}
  ]
}
```
Report stored in Postgres, accessible to examiner/reviewer roles.

### 4.5 Judge service
Unchanged from Phase 1. Queue-driven, sandboxed, autoscaled.
Sandbox rules (never relaxed): no network, read-only rootfs + tmpfs scratch,
non-root uid, CPU/wall-time/memory/pids limits, output-size cap.
Runtime: Docker + gVisor (`--runtime=runsc`) on dedicated node pool.
Verdicts: AC / WA / TLE / MLE / RE / CE per test case + runtime + peak memory.

Note: judge pipeline is also used by the AI service during question
validation and test-case factory (differential testing). Same queue, same
workers — generation jobs use a lower-priority queue lane so live candidate
submissions are never delayed by background generation.

### 4.6 Notification service
Invite emails, reminders, results, report-ready notifications.
One provider interface; SES in prod, console/SMTP stub in dev.

---

## 5. Live follow-up model (Phase 2)

Every question in a session is an event-sourced stream:
```
question_assigned
  → code_snapshot*
  → submission → verdict
  ↘ constraint_modified / followup_pushed
      → new question_version
      → AI factory generates + validates test cases on demand
      → UI shows requirements-diff banner
      → grading binds to version active at submission time
```
Events: append-only rows `(session_id, seq, type, payload,
question_version_id, created_at)`. Phase 1 already stores
`question_version_id` on submissions — event table arrives in Phase 2.

---

## 6. Data layer

**Postgres 16** — system of record. Every tenant table carries `org_id`.
Phase 2 additions:
```
candidate_profile    (session_id, years_exp, domains, seniority, raw_json)
generation_job       (id, type, status, attempts, model, cost, created_at)
generated_question   (question_version_id, generation_job_id, model, cost)
session_evaluation   (session_id, complexity, approach, partial_scores, signals_json)
hiring_report        (session_id, report_json, recommendation, score, created_at)
session_event        (session_id, seq, type, payload, question_version_id, created_at)
```

**Redis** — invite jtis (`gw:` prefix), session state/timers (`ex:` prefix),
WebSocket presence/pub-sub, rate limits.

**S3/MinIO** — submitted code, test-case files, resumes (encrypted at rest),
session replays.

**OpenSearch (Phase 3)** — full-text question search.

---

## 7. Security model

- Two token planes (examiner vs candidate): RS256, distinct private keys,
  distinct `aud` claims. Exam signs; gateway/question verify only.
- Invite tokens: single-use, time-boxed, signed, email-bound; consumed
  atomically on OIDC match.
- RBAC via `require_role(...)` dependency; cross-org access is a tested
  rejection path everywhere.
- Judge sandbox per §4.5; never weakened.
- Secrets via Secrets Manager in prod; nothing in logs.
- Rate limiting per identity at the gateway; request-id in every log line.
- AI service: LLM API keys in Secrets Manager; per-org cost tracking to
  prevent runaway spend; generated content never trusted without validation.
- Resumes stored encrypted at rest (S3 SSE-KMS); only the profile vector
  crosses service boundaries, not the raw document.

---

## 8. Scalability posture

Stateless services → horizontal scale behind ALB. Redis-backed session state.
Queue-buffered judging → autoscaled workers absorb submission bursts.
AI generation jobs are async background tasks — never block the request path.
Two SQS queue lanes: `judge-live` (candidate submissions, high priority) and
`judge-gen` (generation/validation jobs, lower priority). Same worker fleet,
priority handled by polling order.
S3 for all large blobs. CDN for frontend. Postgres scales up → read replicas
→ shard-by-org (org_id on every table from day one).

---

## 9. Phasing

### Phase 1 — Complete ✓
Examiner auth + RBAC, question CRUD + taxonomy + manual test cases,
blueprint builder with seeded sampling, invite + Google OIDC, session
lifecycle, Docker-sandboxed judge (Py/Java/C++), candidate exam UI (Monaco),
examiner console, API gateway, e2e proof. 186 tests passing.

### Production readiness — In progress
CI ✓, branch protection ✓, Redis key-prefix fix ✓
Remaining: RS256 token split, migration race fix, judge gVisor isolation,
frontend prod build, SES sender, real Google OIDC config, TLS, Terraform,
CI/CD deploy pipeline.

### Phase 2 — AI intelligence layer
Each item gets a design note in `docs/` before its Claude Code prompt.
Order:
1. Profile ingestion (PDF + GitHub → CandidateProfile)
2. AI question generator + automated validation loop
3. AI test-case factory (fully automated)
4. Mode 2 scheduling (profile-driven exam composition)
5. Adaptive difficulty engine
6. WebSocket live proctoring + mid-exam follow-ups (event sourcing)
7. AI evaluation (complexity, approach, partial credit, behavioural signals)
8. Hiring signal report generator

### Phase 3
IRT-based difficulty calibration, plagiarism/AI-assistance detection,
candidate-facing results and feedback, employer analytics dashboard,
cohort comparisons, OpenSearch, billing, optional webcam proctoring.