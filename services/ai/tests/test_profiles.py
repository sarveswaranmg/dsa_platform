import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from httpx import AsyncClient

from app.clients.github import get_github_client
from app.llm.client import get_llm_client
from tests.conftest import RaisingGitHubClient, RaisingLLMClient

FIXTURE_PDF = (Path(__file__).parent / "fixtures" / "sample_resume.pdf").read_bytes()


async def _upload_resume(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/profiles/uploads", headers=headers)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    put = httpx.put(
        body["upload_url"].replace("localstack:4566", "localhost:4566"), content=FIXTURE_PDF
    )
    assert put.status_code == 200
    resume_s3_key: str = body["resume_s3_key"]
    return resume_s3_key


async def _wait_terminal(
    client: AsyncClient, headers: dict[str, str], profile_id: str, timeout: float = 10.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await client.get(f"/profiles/{profile_id}", headers=headers)
        assert response.status_code == 200
        body: dict[str, Any] = response.json()
        if body["status"] in ("ready", "failed"):
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"profile {profile_id} never reached a terminal status")


async def test_upload_url_then_full_lifecycle_reaches_ready(
    client: AsyncClient, author: dict[str, str], s3_bucket: None
) -> None:
    resume_s3_key = await _upload_resume(client, author)

    response = await client.post(
        "/profiles", headers=author, json={"resume_s3_key": resume_s3_key}
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "queued"

    profile = await _wait_terminal(client, author, created["id"])
    assert profile["status"] == "ready"
    assert profile["years_exp"] == 5
    assert profile["tech_stack"] == ["Python"]  # MockGitHubClient not consulted (no handle)
    assert profile["error"] is None


async def test_github_handle_signals_flow_into_the_profile(
    client: AsyncClient, author: dict[str, str], s3_bucket: None
) -> None:
    resume_s3_key = await _upload_resume(client, author)

    response = await client.post(
        "/profiles",
        headers=author,
        json={"resume_s3_key": resume_s3_key, "github_handle": "octocat"},
    )
    assert response.status_code == 201

    profile = await _wait_terminal(client, author, response.json()["id"])
    assert profile["status"] == "ready"
    assert profile["tech_stack"] == ["Python", "TypeScript"]  # from MockGitHubClient


async def test_missing_resume_key_ends_in_failed(
    client: AsyncClient, author: dict[str, str], s3_bucket: None
) -> None:
    response = await client.post(
        "/profiles", headers=author, json={"resume_s3_key": "resumes/does-not-exist.pdf"}
    )
    assert response.status_code == 201

    profile = await _wait_terminal(client, author, response.json()["id"])
    assert profile["status"] == "failed"
    assert profile["error"]


async def test_github_client_failure_ends_in_failed(
    app: FastAPI, client: AsyncClient, author: dict[str, str], s3_bucket: None
) -> None:
    app.dependency_overrides[get_github_client] = lambda: RaisingGitHubClient()
    resume_s3_key = await _upload_resume(client, author)

    response = await client.post(
        "/profiles",
        headers=author,
        json={"resume_s3_key": resume_s3_key, "github_handle": "octocat"},
    )
    assert response.status_code == 201

    profile = await _wait_terminal(client, author, response.json()["id"])
    assert profile["status"] == "failed"
    assert profile["error"] == "github boom"


async def test_llm_client_failure_ends_in_failed(
    app: FastAPI, client: AsyncClient, author: dict[str, str], s3_bucket: None
) -> None:
    app.dependency_overrides[get_llm_client] = lambda: RaisingLLMClient()
    resume_s3_key = await _upload_resume(client, author)

    response = await client.post(
        "/profiles", headers=author, json={"resume_s3_key": resume_s3_key}
    )
    assert response.status_code == 201

    profile = await _wait_terminal(client, author, response.json()["id"])
    assert profile["status"] == "failed"
    assert profile["error"] == "llm boom"


async def test_reviewer_cannot_create_profiles(
    client: AsyncClient, reviewer: dict[str, str]
) -> None:
    response = await client.post(
        "/profiles", headers=reviewer, json={"resume_s3_key": "resumes/x.pdf"}
    )
    assert response.status_code == 403

    response = await client.post("/profiles/uploads", headers=reviewer)
    assert response.status_code == 403


async def test_missing_token_rejected(client: AsyncClient) -> None:
    response = await client.get("/profiles/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 401


async def test_unknown_or_other_org_profile_is_404(
    client: AsyncClient, author: dict[str, str], other_org_author: dict[str, str]
) -> None:
    response = await client.get("/profiles/00000000-0000-0000-0000-000000000000", headers=author)
    assert response.status_code == 404

    resume_s3_key = await _upload_resume(client, author)
    created = await client.post(
        "/profiles", headers=author, json={"resume_s3_key": resume_s3_key}
    )
    profile_id = created.json()["id"]

    response = await client.get(f"/profiles/{profile_id}", headers=other_org_author)
    assert response.status_code == 404
