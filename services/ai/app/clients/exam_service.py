import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.exceptions import NotFound, UpstreamServiceError


@dataclass(frozen=True)
class SubmissionRecord:
    mode: str
    language: str
    source: str
    status: str
    summary_verdict: str | None
    created_at: datetime


@dataclass(frozen=True)
class AssignedQuestion:
    ordinal: int
    question_id: uuid.UUID
    question_version_id: uuid.UUID
    submissions: list[SubmissionRecord]


class ExamServiceClient(Protocol):
    """The ai service reaches the exam service over HTTP only (no code
    imports), via the trusted-network internal endpoint — the session-
    evaluation consumer (Phase 2 Slice 7) has no live token to forward, and
    ai has never called exam before this slice."""

    async def list_session_questions(
        self, *, org_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[AssignedQuestion]: ...


class HttpExamServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def list_session_questions(
        self, *, org_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[AssignedQuestion]:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.get(
                    f"/internal/sessions/{session_id}/questions",
                    params={"org_id": str(org_id)},
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("Exam service is unavailable") from exc
        if response.status_code == 404:
            raise NotFound("Session not found")
        if response.status_code != 200:
            raise UpstreamServiceError(f"Exam service returned {response.status_code}")
        return [
            AssignedQuestion(
                ordinal=item["ordinal"],
                question_id=uuid.UUID(item["question_id"]),
                question_version_id=uuid.UUID(item["question_version_id"]),
                submissions=[
                    SubmissionRecord(
                        mode=s["mode"],
                        language=s["language"],
                        source=s["source"],
                        status=s["status"],
                        summary_verdict=s["summary_verdict"],
                        created_at=datetime.fromisoformat(s["created_at"]),
                    )
                    for s in item["submissions"]
                ],
            )
            for item in response.json()
        ]


def get_exam_client() -> ExamServiceClient:
    # FastAPI dependency; overridden in tests with a fake.
    return HttpExamServiceClient(get_settings().exam_service_url)
