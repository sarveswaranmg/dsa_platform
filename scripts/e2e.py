# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "pyjwt>=2.9", "pyotp>=2.9"]
# ///
"""End-to-end proof of the Phase 1 MVP.

Drives the whole platform through the **gateway** (the real edge), in the order
the product actually works:

    create examiner → author a question with test cases → build a blueprint →
    invite a candidate → candidate authenticates → submit a correct and an
    incorrect solution → examiner reads the verdicts.

The one step that cannot run headlessly is the candidate's Google sign-in: the
backend verifies real Google ID tokens and there is deliberately no dev bypass
(see docs/DECISIONS.md). So this script stands in for a completed sign-in by
minting the *same* exam-scoped candidate token the exchange endpoint would
issue — the invite is really created and every downstream call is real. The
rejection paths of the OIDC exchange are covered by the exam service's pytest
suite (services/exam/tests/test_candidate_auth.py).

Prerequisites:
    1. `make dev`  (gateway on :8080, all services, localstack)
    2. the judge worker:  `cd services/judge && uv run python -m app.worker`

Run:
    uv run scripts/e2e.py
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pyotp

GATEWAY_URL = "http://localhost:8080"
# S3 presigned uploads go straight to localstack, bypassing the API by design.
S3_HOST = "http://localhost:4566"
JWT_SECRET = "dev-jwt-secret-change-me-not-for-production-use"
PASSWORD = "correct-horse-battery-staple"
VERDICT_TIMEOUT_S = 90

CORRECT = "a, b = map(int, input().split())\nprint(a + b)\n"
WRONG = "a, b = map(int, input().split())\nprint(a * b)\n"  # multiplies instead


class E2EError(RuntimeError):
    pass


def step(message: str) -> None:
    print(f"\n\033[1m▸ {message}\033[0m")


def ok(message: str) -> None:
    print(f"  \033[32m✓\033[0m {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise E2EError(message)


class Client:
    def __init__(self, base_url: str) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=30.0)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: Any = None,
        expect: int | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self._http.request(method, path, headers=headers, json=json)
        if expect is not None and response.status_code != expect:
            raise E2EError(
                f"{method} {path} -> {response.status_code} "
                f"(expected {expect}): {response.text[:300]}"
            )
        return response


def wait_for_gateway(client: Client) -> None:
    step("Checking the gateway is up")
    for _ in range(10):
        try:
            if client.request("GET", "/healthz").status_code == 200:
                ok("gateway healthy on :8080")
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise E2EError("gateway not reachable on :8080 — is `make dev` running?")


def create_examiner(client: Client) -> str:
    step("Creating an examiner (register → enrol TOTP → login)")
    email = f"examiner+{uuid.uuid4().hex[:10]}@example.com"
    registration = client.request(
        "POST",
        "/auth/register",
        json={"org_name": "Acme Hiring", "email": email, "password": PASSWORD},
        expect=201,
    ).json()
    secret = registration["totp_secret"]
    ok(f"registered {email} as {registration['role']}")

    client.request(
        "POST",
        "/auth/totp/verify",
        json={"email": email, "password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        expect=204,
    )
    ok("TOTP enrolled")

    tokens = client.request(
        "POST",
        "/auth/login",
        json={"email": email, "password": PASSWORD, "totp_code": pyotp.TOTP(secret).now()},
        expect=200,
    ).json()
    ok("logged in with password + TOTP")
    return str(tokens["access_token"])


def author_question(client: Client, token: str) -> str:
    step("Authoring a question with a sample and a hidden test case")
    topic = client.request(
        "POST", "/topics", token=token, json={"name": f"arrays-{uuid.uuid4().hex[:6]}"},
        expect=201,
    ).json()

    question = client.request(
        "POST",
        "/questions",
        token=token,
        json={
            "title": "Add Two Numbers",
            "statement_md": "Read two integers `a` and `b`; print `a + b`.",
            "constraints_md": "1 <= a, b <= 1000",
            "difficulty": 1,
            "time_limit_ms": 2000,
            "memory_limit_mb": 256,
            "topic_ids": [topic["id"]],
            "starter_code": {"python": "# read a and b\n"},
        },
        expect=201,
    ).json()
    qid = question["id"]

    # case 1 is a sample (a Run exercises it); case 2 is hidden.
    for is_sample, stdin, expected in [(True, "2 3", "5"), (False, "40 60", "100")]:
        tc = client.request(
            "POST", f"/questions/{qid}/test-cases", token=token,
            json={"is_sample": is_sample}, expect=201,
        ).json()
        # Direct-to-S3 upload via presigned URLs (never through the API).
        for url, body in [(tc["upload_input_url"], stdin), (tc["upload_output_url"], expected)]:
            put = httpx.put(url.replace("localstack:4566", "localhost:4566"), content=body)
            require(put.status_code == 200, f"S3 upload failed: {put.status_code}")

    client.request("POST", f"/questions/{qid}/publish", token=token, expect=200)
    ok(f"published question {qid[:8]} with 2 test cases (1 sample, 1 hidden)")
    return topic["id"]


def build_blueprint(client: Client, token: str, topic_id: str) -> str:
    step("Building a blueprint")
    blueprint = client.request(
        "POST",
        "/blueprints",
        token=token,
        json={
            "name": "Backend Screen",
            "target_role": "Backend Engineer",
            "experience_band": "senior",
            "total_duration_minutes": 45,
            "topic_mix": [
                {
                    "topic_id": topic_id,
                    "weight": 100,
                    "difficulty_min": 1,
                    "difficulty_max": 1,
                    "question_count": 1,
                }
            ],
        },
        expect=201,
    ).json()
    ok(f"blueprint {blueprint['id'][:8]} (weights sum to 100)")
    return str(blueprint["id"])


def schedule_and_invite(client: Client, token: str, blueprint_id: str) -> dict[str, str]:
    step("Scheduling the exam and inviting the candidate")
    now = datetime.now(UTC)
    candidate_email = f"candidate+{uuid.uuid4().hex[:10]}@example.com"
    exam = client.request(
        "POST",
        "/exams",
        token=token,
        json={
            "candidate_email": candidate_email,
            "blueprint_id": blueprint_id,
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
        },
        expect=201,
    ).json()
    require(bool(exam.get("invite_link")), "no invite link returned")
    ok(f"invite issued to {candidate_email} (status {exam['invite']['status']})")
    ok(f"invite link: {exam['invite_link'][:60]}…")
    return {
        "exam_id": exam["id"],
        "org_id": exam["org_id"],
        "blueprint_version_id": exam["blueprint_version_id"],
        "candidate_email": candidate_email,
    }


def candidate_token(exam: dict[str, str]) -> str:
    step("Candidate authenticates (Google OIDC — stood in for by minting the token)")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),  # invite id
            "org_id": exam["org_id"],
            "exam_id": exam["exam_id"],
            "blueprint_version_id": exam["blueprint_version_id"],
            "candidate_email": exam["candidate_email"],
            "type": "candidate_exam",
            "jti": str(uuid.uuid4()),
            "nbf": now - timedelta(minutes=1),
            "iat": now,
            "exp": now + timedelta(hours=2),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    ok("exam-scoped candidate token obtained")
    return token


def poll_verdict(client: Client, token: str, submission_id: str) -> dict[str, Any]:
    deadline = time.time() + VERDICT_TIMEOUT_S
    while time.time() < deadline:
        body = client.request(
            "GET", f"/candidate/submissions/{submission_id}", token=token, expect=200
        ).json()
        if body["status"] not in {"queued", "running"}:
            return body
        time.sleep(2)
    raise E2EError(
        f"submission {submission_id[:8]} never got a verdict in {VERDICT_TIMEOUT_S}s "
        "— is the judge worker running? (cd services/judge && uv run python -m app.worker)"
    )


def run_exam(client: Client, ctoken: str) -> tuple[str, str]:
    step("Candidate starts the session and submits two solutions")
    session = client.request(
        "POST", "/candidate/session/start", token=ctoken, expect=201
    ).json()
    ordinal = session["questions"][0]["ordinal"]
    ok(f"session started; {len(session['questions'])} question assigned, "
       f"{session['remaining_seconds']}s on the clock")

    results = {}
    for label, source, expected_verdict in [
        ("correct", CORRECT, "AC"),
        ("incorrect", WRONG, "WA"),
    ]:
        submission = client.request(
            "POST",
            f"/candidate/session/questions/{ordinal}/submissions",
            token=ctoken,
            json={"language": "python", "source": source, "mode": "submit"},
            expect=201,
        ).json()
        verdict = poll_verdict(client, ctoken, submission["id"])
        require(
            verdict["summary_verdict"] == expected_verdict,
            f"{label} solution: expected {expected_verdict}, got {verdict['summary_verdict']}",
        )
        ok(f"{label} solution judged → {verdict['summary_verdict']} "
           f"({len(verdict['cases'])} cases)")
        results[label] = submission["id"]
    return results["correct"], results["incorrect"]


def review_results(
    client: Client, token: str, exam_id: str, correct_id: str, wrong_id: str
) -> None:
    step("Examiner reviews the results")
    submissions = client.request(
        "GET", f"/exams/{exam_id}/submissions", token=token, expect=200
    ).json()
    verdicts = {s["id"]: s["summary_verdict"] for s in submissions}
    require(verdicts.get(correct_id) == "AC", "results missing the AC submission")
    require(verdicts.get(wrong_id) == "WA", "results missing the WA submission")
    ok(f"results list shows {len(submissions)} submissions: AC and WA")

    detail = client.request("GET", f"/submissions/{correct_id}", token=token, expect=200).json()
    require(detail["source"] == CORRECT, "submitted code not returned for review")
    require(detail["cases"], "no per-case verdicts on the detail view")
    ok("examiner can read the submitted code and per-case verdicts")


def main() -> int:
    client = Client(GATEWAY_URL)
    try:
        wait_for_gateway(client)
        examiner = create_examiner(client)
        topic_id = author_question(client, examiner)
        blueprint_id = build_blueprint(client, examiner, topic_id)
        exam = schedule_and_invite(client, examiner, blueprint_id)
        ctoken = candidate_token(exam)
        correct_id, wrong_id = run_exam(client, ctoken)
        review_results(client, examiner, exam["exam_id"], correct_id, wrong_id)
    except E2EError as error:
        print(f"\n\033[31m✗ E2E FAILED:\033[0m {error}")
        return 1
    print("\n\033[1;32m✓ E2E PASSED — the full MVP flow works end to end.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
