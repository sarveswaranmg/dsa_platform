import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.exceptions import NotFound, UpstreamServiceError


@dataclass(frozen=True)
class QuestionCreated:
    question_id: uuid.UUID
    version_id: uuid.UUID
    version_number: int


@dataclass(frozen=True)
class VersionContent:
    version_id: uuid.UUID
    question_id: uuid.UUID
    version_number: int
    title: str
    statement_md: str
    constraints_md: str
    difficulty: int
    time_limit_ms: int
    memory_limit_mb: int
    starter_code: dict[str, str]


@dataclass(frozen=True)
class TestCaseUpload:
    __test__ = False  # not a pytest test class despite the name

    id: uuid.UUID
    ordinal: int
    upload_input_url: str
    upload_output_url: str


class QuestionServiceClient(Protocol):
    """The ai service reaches the question service over HTTP only (no code
    imports), via the trusted-network internal endpoint — the generation
    results consumer has no live examiner bearer token to forward by the
    time a job succeeds."""

    async def create_question(
        self,
        *,
        org_id: uuid.UUID,
        title: str,
        statement_md: str,
        constraints_md: str,
        difficulty: int,
        time_limit_ms: int,
        memory_limit_mb: int,
        starter_code: dict[str, str],
        topic_ids: list[uuid.UUID],
    ) -> QuestionCreated: ...

    async def create_test_case_upload(
        self, *, org_id: uuid.UUID, question_id: uuid.UUID, is_sample: bool = False
    ) -> TestCaseUpload: ...

    async def get_version_content(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> VersionContent: ...


class HttpQuestionServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def create_question(
        self,
        *,
        org_id: uuid.UUID,
        title: str,
        statement_md: str,
        constraints_md: str,
        difficulty: int,
        time_limit_ms: int,
        memory_limit_mb: int,
        starter_code: dict[str, str],
        topic_ids: list[uuid.UUID],
    ) -> QuestionCreated:
        body = {
            "org_id": str(org_id),
            "title": title,
            "statement_md": statement_md,
            "constraints_md": constraints_md,
            "difficulty": difficulty,
            "time_limit_ms": time_limit_ms,
            "memory_limit_mb": memory_limit_mb,
            "starter_code": starter_code,
            "topic_ids": [str(t) for t in topic_ids],
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.post("/internal/questions", json=body)
        except httpx.HTTPError as exc:
            raise UpstreamServiceError() from exc
        if response.status_code != 201:
            raise UpstreamServiceError(f"Question service returned {response.status_code}")
        item = response.json()
        return QuestionCreated(
            question_id=uuid.UUID(item["question_id"]),
            version_id=uuid.UUID(item["version_id"]),
            version_number=item["version_number"],
        )

    async def create_test_case_upload(
        self, *, org_id: uuid.UUID, question_id: uuid.UUID, is_sample: bool = False
    ) -> TestCaseUpload:
        body = {"org_id": str(org_id), "is_sample": is_sample}
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.post(
                    f"/internal/questions/{question_id}/test-cases", json=body
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError() from exc
        if response.status_code != 201:
            raise UpstreamServiceError(f"Question service returned {response.status_code}")
        item = response.json()
        return TestCaseUpload(
            id=uuid.UUID(item["id"]),
            ordinal=item["ordinal"],
            upload_input_url=item["upload_input_url"],
            upload_output_url=item["upload_output_url"],
        )

    async def get_version_content(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> VersionContent:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.get(
                    f"/internal/question-versions/{version_id}",
                    params={"org_id": str(org_id)},
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError() from exc
        if response.status_code == 404:
            raise NotFound("Question version not found")
        if response.status_code != 200:
            raise UpstreamServiceError(f"Question service returned {response.status_code}")
        item = response.json()
        return VersionContent(
            version_id=uuid.UUID(item["version_id"]),
            question_id=uuid.UUID(item["question_id"]),
            version_number=item["version_number"],
            title=item["title"],
            statement_md=item["statement_md"],
            constraints_md=item["constraints_md"],
            difficulty=item["difficulty"],
            time_limit_ms=item["time_limit_ms"],
            memory_limit_mb=item["memory_limit_mb"],
            starter_code=item["starter_code"],
        )


def get_question_client() -> QuestionServiceClient:
    # FastAPI dependency; overridden in tests with a fake.
    return HttpQuestionServiceClient(get_settings().question_service_url)
