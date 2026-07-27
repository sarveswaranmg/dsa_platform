# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "pyjwt>=2.9", "pyotp>=2.9", "cryptography>=42"]
# ///
"""Populates a fresh dev database with browsable data for the examiner console.

Unlike scripts/e2e.py (which proves the whole pipeline works, including a
judged submission), this script exists to make the console *look* like a real
account: several topics, a spread of published questions, a couple of
blueprints, and a couple of scheduled/invited exams — enough to click around
Question Bank, Blueprint Builder, and Exam Schedule without everything being
empty.

Prerequisites:
    make dev   (gateway on :8080, all services, localstack)

Usage:
    # Fresh demo org + admin examiner (prints the login + TOTP secret to use
    # in the console at http://localhost:5173/console/login):
    uv run scripts/seed.py

    # Seed into an examiner account you already created via the console's
    # /console/register page (so the data shows up when *you* log in):
    uv run scripts/seed.py --email you@example.com --password '...' --totp-secret ABCD...

    # Also drive one exam through a real candidate submission (needs the
    # judge worker running: cd services/judge && uv run python -m app.worker)
    uv run scripts/seed.py --with-submissions
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pyotp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e import (  # noqa: E402
    Client,
    E2EError,
    GATEWAY_URL,
    candidate_token,
    ok,
    poll_verdict,
    require,
    step,
    wait_for_gateway,
)

DEFAULT_ORG_NAME = "Seed Org"
DEFAULT_EMAIL = "seed@example.com"
DEFAULT_PASSWORD = "correct-horse-battery-staple"

# (topic, [(title, statement_md, constraints_md, difficulty, starter, [(stdin, expected, is_sample)])])
TOPICS: list[tuple[str, list[tuple[str, str, str, int, str, list[tuple[str, str, bool]]]]]] = [
    (
        "arrays",
        [
            (
                "Two Sum",
                "Given an array of integers and a target, print the indices of the "
                "two numbers that add up to the target.",
                "2 <= n <= 10^4",
                2,
                "# read n, the array, and the target\n",
                [("4\n2 7 11 15\n9", "0 1", True), ("3\n3 2 4\n6", "1 2", False)],
            ),
            (
                "Maximum Subarray",
                "Given an array of integers, print the largest sum of any "
                "contiguous subarray.",
                "1 <= n <= 10^5",
                3,
                "# read n and the array\n",
                [("5\n-2 1 -3 4 -1\n", "4", True), ("1\n1\n", "1", False)],
            ),
        ],
    ),
    (
        "strings",
        [
            (
                "Valid Palindrome",
                "Given a string, print `true` if it reads the same forwards and "
                "backwards (ignoring case), else `false`.",
                "1 <= len(s) <= 10^5",
                1,
                "# read s\n",
                [("racecar", "true", True), ("hello", "false", False)],
            ),
            (
                "Longest Substring Without Repeating Characters",
                "Given a string, print the length of the longest substring "
                "without repeating characters.",
                "0 <= len(s) <= 5 * 10^4",
                3,
                "# read s\n",
                [("abcabcbb", "3", True), ("bbbbb", "1", False)],
            ),
        ],
    ),
    (
        "trees",
        [
            (
                "Maximum Depth of Binary Tree",
                "Given a binary tree in level order (using `null` for missing "
                "nodes), print its maximum depth.",
                "0 <= nodes <= 10^4",
                1,
                "# read the level-order tree\n",
                [("3 9 20 null null 15 7", "3", True), ("", "0", False)],
            ),
            (
                "Binary Tree Inorder Traversal",
                "Given a binary tree in level order, print its inorder "
                "traversal.",
                "0 <= nodes <= 10^4",
                2,
                "# read the level-order tree\n",
                [("1 null 2 3", "1 3 2", True), ("", "", False)],
            ),
        ],
    ),
    (
        "graphs",
        [
            (
                "Number of Islands",
                "Given a grid of `1`s (land) and `0`s (water), print the number "
                "of islands.",
                "1 <= rows, cols <= 300",
                3,
                "# read the grid\n",
                [("3 3\n110\n110\n001", "2", True), ("1 1\n1", "1", False)],
            ),
            (
                "Course Schedule",
                "Given a number of courses and a list of prerequisite pairs, "
                "print `true` if all courses can be finished, else `false`.",
                "1 <= numCourses <= 2000",
                3,
                "# read numCourses and the prerequisite pairs\n",
                [("2\n1 0", "true", True), ("2\n1 0\n0 1", "false", False)],
            ),
        ],
    ),
    (
        "dynamic-programming",
        [
            (
                "Climbing Stairs",
                "Given a number of steps `n`, print how many distinct ways "
                "there are to climb to the top, taking 1 or 2 steps at a time.",
                "1 <= n <= 45",
                1,
                "# read n\n",
                [("2", "2", True), ("3", "3", False)],
            ),
            (
                "Coin Change",
                "Given a set of coin denominations and an amount, print the "
                "fewest number of coins needed to make that amount, or -1.",
                "1 <= coins.length <= 12",
                3,
                "# read the coins and the amount\n",
                [("3\n1 2 5\n11", "3", True), ("1\n2\n3", "-1", False)],
            ),
        ],
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-name", default=DEFAULT_ORG_NAME)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--totp-secret",
        default=None,
        help="Reuse an already-registered examiner instead of creating a new org.",
    )
    parser.add_argument(
        "--with-submissions",
        action="store_true",
        help="Also drive one exam through a judged AC + WA submission (needs the judge worker).",
    )
    return parser.parse_args()


def register_or_login(client: Client, args: argparse.Namespace) -> tuple[str, str]:
    step("Setting up the examiner account")
    if args.totp_secret:
        secret = args.totp_secret
        ok(f"reusing existing account {args.email}")
    else:
        response = client.request(
            "POST",
            "/auth/register",
            json={"org_name": args.org_name, "email": args.email, "password": args.password},
        )
        if response.status_code == 409:
            raise E2EError(
                f"{args.email} already exists — pass --totp-secret (and matching "
                "--email/--password) to seed into that account instead of registering a new one."
            )
        require(response.status_code == 201, f"register failed: {response.text[:300]}")
        secret = response.json()["totp_secret"]
        ok(f"registered {args.email} in org '{args.org_name}'")

        client.request(
            "POST",
            "/auth/totp/verify",
            json={"email": args.email, "password": args.password, "code": pyotp.TOTP(secret).now()},
            expect=204,
        )
        ok("TOTP enrolled")

    tokens = client.request(
        "POST",
        "/auth/login",
        json={
            "email": args.email,
            "password": args.password,
            "totp_code": pyotp.TOTP(secret).now(),
        },
        expect=200,
    ).json()
    ok("logged in with password + TOTP")
    return str(tokens["access_token"]), secret


def seed_topics_and_questions(client: Client, token: str) -> dict[str, str]:
    # Idempotent: topic names are unique per org (a repeat run against the
    # same account would otherwise 500 on the duplicate-name constraint),
    # and skipping questions whose title already exists avoids piling up
    # clutter on repeat runs too.
    step(f"Creating {len(TOPICS)} topics with {sum(len(qs) for _, qs in TOPICS)} questions")
    existing_topics = {t["name"]: t["id"] for t in client.request(
        "GET", "/topics", token=token, expect=200
    ).json()}
    existing_titles = {
        q["title"]
        for q in client.request("GET", "/questions", token=token, expect=200).json()
    }

    topic_ids: dict[str, str] = {}
    for name, questions in TOPICS:
        if name in existing_topics:
            topic_ids[name] = existing_topics[name]
            ok(f"[{name}] topic already exists, reusing it")
        else:
            topic = client.request(
                "POST", "/topics", token=token, json={"name": name}, expect=201
            ).json()
            topic_ids[name] = topic["id"]

        for title, statement, constraints, difficulty, starter, cases in questions:
            if title in existing_titles:
                ok(f"[{name}] '{title}' already exists, skipping")
                continue
            question = client.request(
                "POST",
                "/questions",
                token=token,
                json={
                    "title": title,
                    "statement_md": statement,
                    "constraints_md": constraints,
                    "difficulty": difficulty,
                    "time_limit_ms": 2000,
                    "memory_limit_mb": 256,
                    "topic_ids": [topic["id"]],
                    "starter_code": {"python": starter},
                },
                expect=201,
            ).json()
            qid = question["id"]

            for stdin, expected, is_sample in cases:
                tc = client.request(
                    "POST",
                    f"/questions/{qid}/test-cases",
                    token=token,
                    json={"is_sample": is_sample},
                    expect=201,
                ).json()
                for url, body in [
                    (tc["upload_input_url"], stdin),
                    (tc["upload_output_url"], expected),
                ]:
                    put = httpx.put(url.replace("localstack:4566", "localhost:4566"), content=body)
                    require(put.status_code == 200, f"S3 upload failed: {put.status_code}")

            client.request("POST", f"/questions/{qid}/publish", token=token, expect=200)
            ok(f"[{name}] published '{title}' (difficulty {difficulty}, {len(cases)} test cases)")

    return topic_ids


def seed_blueprints(client: Client, token: str, topic_ids: dict[str, str]) -> list[dict[str, str]]:
    step("Building blueprints")
    specs = [
        (
            "Backend Screen — Mid",
            "Backend Engineer",
            "mid",
            60,
            [
                {"topic_id": topic_ids["arrays"], "weight": 50, "difficulty_min": 1, "difficulty_max": 2, "question_count": 1},
                {"topic_id": topic_ids["strings"], "weight": 50, "difficulty_min": 1, "difficulty_max": 2, "question_count": 1},
            ],
        ),
        (
            "Backend Screen — Senior",
            "Backend Engineer",
            "senior",
            90,
            [
                {"topic_id": topic_ids["trees"], "weight": 30, "difficulty_min": 1, "difficulty_max": 3, "question_count": 1},
                {"topic_id": topic_ids["graphs"], "weight": 40, "difficulty_min": 2, "difficulty_max": 3, "question_count": 1},
                {"topic_id": topic_ids["dynamic-programming"], "weight": 30, "difficulty_min": 1, "difficulty_max": 3, "question_count": 1},
            ],
        ),
    ]
    blueprints = []
    for name, role, band, duration, topic_mix in specs:
        blueprint = client.request(
            "POST",
            "/blueprints",
            token=token,
            json={
                "name": name,
                "target_role": role,
                "experience_band": band,
                "total_duration_minutes": duration,
                "topic_mix": topic_mix,
            },
            expect=201,
        ).json()
        blueprints.append(blueprint)
        ok(f"blueprint '{name}' ({band}, {duration}m)")
    return blueprints


def seed_exams(client: Client, token: str, blueprints: list[dict[str, str]]) -> list[dict[str, str]]:
    step("Scheduling exams and inviting candidates")
    exams = []
    now = datetime.now(UTC)
    for blueprint in blueprints:
        candidate_email = f"candidate+{uuid.uuid4().hex[:8]}@example.com"
        exam = client.request(
            "POST",
            "/exams",
            token=token,
            json={
                "candidate_email": candidate_email,
                "blueprint_id": blueprint["id"],
                "starts_at": (now - timedelta(minutes=1)).isoformat(),
                "ends_at": (now + timedelta(hours=2)).isoformat(),
            },
            expect=201,
        ).json()
        exams.append(exam)
        ok(f"invited {candidate_email} to '{blueprint['name']}'")
    return exams


def seed_submission(client: Client, exam: dict[str, str]) -> None:
    step("Driving one exam through a judged submission (needs the judge worker)")
    ctoken = candidate_token(exam)
    session = client.request(
        "POST", "/candidate/session/start", token=ctoken, expect=201
    ).json()
    ordinal = session["questions"][0]["ordinal"]
    submission = client.request(
        "POST",
        f"/candidate/session/questions/{ordinal}/submissions",
        token=ctoken,
        json={"language": "python", "source": "print('seeded')\n", "mode": "submit"},
        expect=201,
    ).json()
    verdict = poll_verdict(client, ctoken, submission["id"])
    ok(f"submission judged → {verdict['summary_verdict']}")


def main() -> int:
    args = parse_args()
    client = Client(GATEWAY_URL)
    try:
        wait_for_gateway(client)
        token, secret = register_or_login(client, args)
        topic_ids = seed_topics_and_questions(client, token)
        blueprints = seed_blueprints(client, token, topic_ids)
        exams = seed_exams(client, token, blueprints)
        if args.with_submissions:
            seed_submission(client, exams[0])
    except E2EError as error:
        print(f"\n\033[31m✗ SEED FAILED:\033[0m {error}")
        return 1

    print("\n\033[1;32m✓ Seed complete.\033[0m")
    print(f"  Log in at http://localhost:5173/console/login with:")
    print(f"    email:    {args.email}")
    print(f"    password: {args.password}")
    if not args.totp_secret:
        print(f"    TOTP secret (add to an authenticator app): {secret}")
        print(f"    current code right now: {pyotp.TOTP(secret).now()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
