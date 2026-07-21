import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.exceptions import UpstreamServiceError


@dataclass(frozen=True)
class QuestionRef:
    id: uuid.UUID
    difficulty: int


@dataclass(frozen=True)
class TestCaseKeys:
    __test__ = False  # not a pytest test class despite the name

    ordinal: int
    input_s3_key: str
    expected_output_s3_key: str


class QuestionServiceClient(Protocol):
    """The exam service reaches the question service over HTTP only (no code
    imports). Implementations forward the caller's bearer token so the
    question service applies org scoping and role checks itself."""

    async def list_published_questions(
        self, *, authorization: str, topic_id: uuid.UUID, difficulty: int
    ) -> list[QuestionRef]: ...

    async def list_version_test_cases(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> list[TestCaseKeys]: ...


class HttpQuestionServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def list_published_questions(
        self, *, authorization: str, topic_id: uuid.UUID, difficulty: int
    ) -> list[QuestionRef]:
        params: dict[str, str | int] = {
            "topic_id": str(topic_id),
            "difficulty": difficulty,
            "status": "published",
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.get(
                    "/questions", params=params, headers={"Authorization": authorization}
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError() from exc
        if response.status_code != 200:
            raise UpstreamServiceError(
                f"Question service returned {response.status_code}"
            )
        return [
            QuestionRef(id=uuid.UUID(item["id"]), difficulty=item["difficulty"])
            for item in response.json()
        ]

    async def list_version_test_cases(
        self, *, org_id: uuid.UUID, version_id: uuid.UUID
    ) -> list[TestCaseKeys]:
        # Internal endpoint (trusted network, no examiner auth) → test-case S3
        # keys for a pinned version, so the exam service can build a judge job.
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.get(
                    f"/internal/question-versions/{version_id}/test-cases",
                    params={"org_id": str(org_id)},
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError() from exc
        if response.status_code != 200:
            raise UpstreamServiceError(f"Question service returned {response.status_code}")
        return [
            TestCaseKeys(
                ordinal=item["ordinal"],
                input_s3_key=item["input_s3_key"],
                expected_output_s3_key=item["expected_output_s3_key"],
            )
            for item in response.json()
        ]


def get_question_client() -> QuestionServiceClient:
    # FastAPI dependency; overridden in tests with a fake.
    return HttpQuestionServiceClient(get_settings().question_service_url)
