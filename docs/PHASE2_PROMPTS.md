# Phase 2 build plan — AI intelligence layer

Same rules as Phase 1: one slice = one Claude Code session, Plan mode first,
commit after each accepted slice, PR through CI before merging. Write the
design note in `docs/` before starting each slice — Claude Code reads it
in Plan mode before proposing anything.

---

## Slice 1 — Profile ingestion pipeline

**Write first:** `docs/design-profile-ingestion.md`
```
Input: resume PDF (S3 presigned upload) + optional GitHub handle
Output: CandidateProfile {years_exp, domains[], tech_stack[],
        seniority_estimate, weak_signals[], strong_signals[]}
Stored: candidate_profile table, linked to exam session
```

**Prompt:**
> Create `services/ai` as a new FastAPI service copying the exam service
> scaffold (uv, async SQLAlchemy, Alembic, pytest, docker-compose entry).
> Implement the profile ingestion pipeline per
> `docs/design-profile-ingestion.md`:
> 1) `POST /profiles` — accepts resume PDF as S3 key + optional GitHub
>    handle, enqueues a background job, returns a job id.
> 2) Background job: extract PDF text (pdfplumber; fallback pytesseract
>    for scanned), call GitHub API for top languages + repo signals if
>    handle provided, call Anthropic Claude API with structured output to
>    produce a `CandidateProfile` Pydantic model, store in
>    `candidate_profile` table.
> 3) `GET /profiles/{job_id}` — returns job status and profile when ready.
> 4) LLM calls go through a single `LLMClient` abstraction in
>    `app/llm/client.py` with retry logic and cost logging per call.
> 5) Anthropic API key via `ANTHROPIC_API_KEY` env var; fail fast on
>    startup if missing in production.
> Tests: mock LLM + GitHub calls; test PDF extraction with a fixture PDF;
> test job lifecycle. `make test && make lint` must pass. Plan first.

**Commit:** `feat(ai): profile ingestion pipeline`

---

## Slice 2 — AI question generator + validation loop

**Write first:** `docs/design-question-generation.md`
```
Input: {topic_id, difficulty_band, language_targets[]}
Output: validated question version stored in question service
Validation: differential testing via judge pipeline, agreement >= 95%
Max attempts: 3 before marking generation_job as failed
```

**Prompt:**
> In `services/ai`, implement the question generation pipeline per
> `docs/design-question-generation.md`:
> 1) `POST /questions/generate` — accepts topic + difficulty band +
>    language targets, enqueues generation job, returns job id.
> 2) Generation job steps:
>    a) LLM (claude-sonnet-4-6) generates: problem statement, constraints,
>       examples, starter code per language — strict JSON schema output.
>    b) Static validation: constraints parseable, examples match declared
>       I/O format, no self-contradictions.
>    c) Second LLM call (claude-haiku-4-5): generate reference solution
>       (optimal, with complexity annotation).
>    d) Third LLM call (different temperature/prompt): generate brute-force
>       solution independently.
>    e) Generate 100 random inputs within constraints (constraint-aware
>       random input generator, not LLM).
>    f) Submit reference + brute-force against all inputs to judge pipeline
>       via `judge-gen` SQS queue (lower priority than `judge-live`).
>    g) Collect verdicts: if agreement < 95% → discard, retry (max 3
>       attempts). On 3rd failure → mark job failed, log disagreement cases.
>    h) On success: POST to question service to create a new question
>       version with the generated content.
> 3) `GET /questions/generate/{job_id}` — status + question_version_id
>    when complete.
> 4) All LLM calls through `LLMClient`; log model, tokens, cost per call
>    to `generation_job` table.
> Tests: mock LLM + judge responses; test retry logic; test 95% threshold;
> test static validation rejects bad constraints. Plan first.

**Commit:** `feat(ai): question generator with differential validation`

---

## Slice 3 — AI test-case factory

**Write first:** `docs/design-testcase-factory.md`
```
Input: question_version_id (with reference + brute-force solutions)
Output: validated test cases stored in question service (S3 + metadata)
Case types: edge, adversarial, stress
Validation: same differential testing as question generation
```

**Prompt:**
> In `services/ai`, implement the test-case factory per
> `docs/design-testcase-factory.md`:
> 1) `POST /test-cases/generate` — accepts question_version_id, enqueues
>    factory job, returns job id.
> 2) Factory job:
>    a) Fetch question version from question service.
>    b) LLM generates 30 candidate cases: 10 edge, 10 adversarial,
>       10 stress — each as {input, description, case_type}.
>    c) Constraint validator: parse each input against declared constraints;
>       reject malformed inputs.
>    d) Submit all valid inputs to judge pipeline (`judge-gen` queue)
>       against reference + brute-force solutions.
>    e) Keep only cases where both solutions agree on output.
>    f) Upload kept cases to S3; POST metadata to question service to
>       attach test cases to the question version.
>    g) Log discarded cases (disagreements) to `generation_job.discard_log`.
> 3) `GET /test-cases/generate/{job_id}` — status + case count when done.
> 4) On-demand variant for mid-exam follow-ups: same pipeline but runs
>    synchronously with a 30-second timeout (fewer cases: 10 total).
> Tests: mock LLM + judge; test constraint validator with bad inputs;
> test discard logic; test on-demand variant timeout. Plan first.

**Commit:** `feat(ai): test-case factory with differential validation`

---

## Slice 4 — Mode 2: profile-driven exam composition

**Write first:** `docs/design-mode2-scheduling.md`
```
Input: candidate_profile + target_role + seniority_band
Output: auto-generated blueprint {topic_mix, difficulty_band, duration}
        → triggers question generation for each slot
Flow: exam service calls ai service → ai service returns blueprint spec
      → exam service creates blueprint → ai service generates questions
```

**Prompt:**
> Implement Mode 2 (profile-driven) exam scheduling across `services/exam`
> and `services/ai` per `docs/design-mode2-scheduling.md`:
>
> In `services/ai`:
> 1) `POST /blueprints/generate` — accepts candidate_profile_id +
>    target_role + seniority_band. LLM call produces a blueprint spec:
>    topic_mix[], difficulty_band, recommended_duration, rationale.
>    Returns the spec (not stored — exam service owns blueprints).
> 2) `POST /exams/generate` — accepts blueprint spec + language_targets.
>    Triggers one question generation job per blueprint slot (parallel).
>    Returns exam_generation_id + list of question generation job ids.
> 3) `GET /exams/generate/{id}` — aggregate status across all question
>    jobs; ready when all succeed.
>
> In `services/exam`:
> 1) Add `POST /exams/schedule-ai` endpoint — examiner provides candidate
>    email + profile_id + target_role + seniority_band. Service calls ai
>    service to get blueprint spec, creates a blueprint record, calls ai
>    service to generate questions, polls until ready, creates the exam.
>    Returns exam_id + a "pending generation" status while jobs run.
> 2) Examiner can GET the pending exam and optionally override any
>    generated question before the invite is sent.
> 3) Invite only sent once all questions are ready and examiner confirms
>    (or after a configurable auto-confirm timeout).
>
> Tests: mock ai service responses; test full scheduling flow; test
> examiner override before invite; test auto-confirm timeout. Plan first.

**Commit:** `feat(exam,ai): Mode 2 profile-driven exam scheduling`

---

## Slice 5 — Adaptive difficulty engine

**Write first:** `docs/design-adaptive-difficulty.md`
```
Signals: time_to_ac, complexity_detected, wa_count, tle_count
Rules (simplified IRT):
  - AC in < 30% allotted time + O(n log n) or better → raise difficulty +1
  - AC in < 30% allotted time + suboptimal → raise difficulty +0.5
  - No AC past 60% time → hold difficulty
  - No AC past 80% time → lower difficulty -1
  - Calibrates from real session data in Phase 3 (static rules for now)
```

**Prompt:**
> In `services/ai`, implement the adaptive difficulty engine per
> `docs/design-adaptive-difficulty.md`:
> 1) `POST /difficulty/signal` — called by exam service after each
>    question verdict. Accepts: session_id, question_version_id,
>    time_elapsed_pct, verdict, complexity_hint (from AI evaluation if
>    available, else null). Returns: next_difficulty_band.
> 2) Difficulty state tracked in Redis (key: `ai:diff:{session_id}`)
>    as a float 1.0–5.0 updated after each signal.
> 3) Static rule engine per design note (IRT calibration in Phase 3).
> 4) Exam service calls this endpoint after each verdict and uses the
>    returned difficulty band when requesting the next question from the
>    AI service.
> Update `services/exam` session lifecycle to call `/difficulty/signal`
> after each verdict and pass the result to the next question selection.
> Tests: test each rule branch; test difficulty bounds (never < 1, > 5);
> test Redis state persistence across signals. Plan first.

**Commit:** `feat(ai,exam): adaptive difficulty engine`

---

## Slice 6 — WebSocket live proctoring + mid-exam follow-ups

**Write first:** `docs/design-live-proctoring.md`
```
Event sourcing: append-only session_event table
Event types: question_assigned, code_snapshot, submission, verdict,
             constraint_modified, followup_pushed
Proctor flow: proctor sees live code snapshots → pushes follow-up →
              new question version created → AI factory generates test
              cases on demand → candidate sees requirements-diff banner
```

**Prompt:**
> Implement live proctoring and mid-exam follow-ups in `services/exam`
> and `services/ai` per `docs/design-live-proctoring.md`:
>
> In `services/exam`:
> 1) Create `session_event` table (append-only, see architecture §6).
> 2) Emit events for: question_assigned, code_snapshot (every 30s from
>    candidate WebSocket), submission, verdict.
> 3) Proctor WebSocket channel: proctor joins session as observer; receives
>    all events in real time (code snapshots, verdicts). Gated to
>    `proctor` role.
> 4) `POST /sessions/{id}/followup` (proctor only) — accepts modified
>    constraint text. Service: creates new question version with the
>    modified constraint, calls ai service on-demand test-case factory
>    (30s timeout variant), attaches new test cases to new version, emits
>    `followup_pushed` event to candidate WebSocket with a diff of changed
>    constraints. Grading for subsequent submissions uses new version id.
> 5) Session replay: `GET /sessions/{id}/replay` returns full event stream
>    ordered by seq. Gated to `reviewer` role.
>
> Frontend (candidate exam UI):
> 6) Add requirements-diff banner component: appears when a `followup_pushed`
>    WebSocket event arrives; shows changed constraint diff; dismissible.
>
> Tests: test event ordering; test proctor isolation (can observe, cannot
> submit); test follow-up creates new version; test grading binds to
> correct version; test replay completeness. Plan first.

**Commit:** `feat(exam,frontend): live proctoring, follow-ups, event sourcing`

---

## Slice 7 — AI evaluation

**Write first:** `docs/design-ai-evaluation.md`
```
Runs async after session ends — never blocks result delivery
Inputs: submitted code per question, verdict, run history
Outputs: complexity, approach, partial_score, behavioural_signals
Stored: session_evaluation table
```

**Prompt:**
> In `services/ai`, implement async session evaluation per
> `docs/design-ai-evaluation.md`:
> 1) Subscribe to a `session-complete` SQS event published by exam service
>    when a session ends.
> 2) For each submitted question in the session:
>    a) AST-based complexity analysis: parse submitted code (ast module for
>       Python; basic heuristics for Java/C++), detect loop nesting depth,
>       classify as O(n), O(n log n), O(n²), etc.
>    b) LLM call: given problem statement + submitted code → identify
>       algorithm family (BFS, DP, two-pointer, etc.), assess whether
>       approach is optimal, identify specific bug if WA.
>    c) Partial credit score (0.0–1.0): AC=1.0, WA with correct approach
>       and minor bug=0.7, WA with correct approach and major bug=0.4,
>       fundamentally wrong approach=0.1, no submission=0.0.
>    d) Behavioural signals: runs before AC, did candidate test edge cases
>       (detected from run history inputs), response pattern to TLE/WA.
> 3) Store all signals in `session_evaluation` table.
> 4) Publish `evaluation-complete` event to trigger report generation.
> Tests: mock LLM; test complexity classifier against known code snippets;
> test partial credit rules; test with no submission. Plan first.

**Commit:** `feat(ai): async session evaluation pipeline`

---

## Slice 8 — Hiring signal report

**Write first:** `docs/design-hiring-report.md`
```
Input: session + session_evaluation + candidate_profile
Output: HiringReport JSON (see architecture §4.4.6)
Accessible to: reviewer and admin roles via exam service
Delivered: email notification when ready
```

**Prompt:**
> In `services/ai`, implement hiring report generation per
> `docs/design-hiring-report.md`:
> 1) Subscribe to `evaluation-complete` SQS event.
> 2) Fetch session, session_evaluation, candidate_profile from their
>    respective services over HTTP.
> 3) LLM call: synthesise all signals into a structured `HiringReport`
>    (strict JSON schema per architecture §4.4.6). Prompt must instruct
>    the model to cite specific evidence from the session for every claim.
> 4) Validate the report schema with Pydantic before storing.
> 5) Store in `hiring_report` table; POST to exam service to attach to the
>    session record.
> 6) Trigger notification service to email examiner/reviewer that the
>    report is ready with a deep link.
>
> In `services/exam`:
> 7) `GET /sessions/{id}/report` — returns hiring report. Gated to
>    `reviewer` and `admin` roles.
>
> In `frontend/` (examiner console):
> 8) Add a report view: seniority match badge, strong/weak area tags,
>    overall score bar, recommendation chip (proceed/maybe/reject),
>    evidence table per question.
>
> Tests: mock LLM + downstream services; test schema validation rejects
> malformed LLM output; test role gating; test report view renders.
> Plan first.

**Commit:** `feat(ai,exam,frontend): hiring signal report`

---

## Standing instructions (apply to every slice)

- Plan mode first; edit the plan before approving.
- `make test && make lint` after implementation; fix before showing diffs.
- Every LLM call goes through `LLMClient` — never call the API directly
  from a router or service layer.
- Two SQS queue lanes always: `judge-live` (candidate submissions) and
  `judge-gen` (generation jobs). Never mix them.
- AI service never stores resumes or raw code — only the extracted profile
  vector and evaluation signals.
- Small commits; never bundle two slices.
- Write the `docs/design-*.md` note before each session, not during.
- After each slice, add a DECISIONS.md entry for any non-obvious choice.

## After Phase 2 is complete

- Update `CLAUDE.md`: mark Phase 2 done, add Phase 3 items to the
  production readiness section.
- Record a new demo video showing the full AI flow: resume upload →
  profile extraction → auto-generated exam → candidate solves →
  AI evaluation → hiring report delivered.
- Then Phase 3: IRT calibration, plagiarism detection, analytics,
  billing.