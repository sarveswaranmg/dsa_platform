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


class QuestionServiceClient(Protocol):
    """The exam service reaches the question service over HTTP only (no code
    imports). Implementations forward the caller's bearer token so the
    question service applies org scoping and role checks itself."""

    async def list_published_questions(
        self, *, authorization: str, topic_id: uuid.UUID, difficulty: int
    ) -> list[QuestionRef]: ...


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


def get_question_client() -> QuestionServiceClient:
    # FastAPI dependency; overridden in tests with a fake.
    return HttpQuestionServiceClient(get_settings().question_service_url)
