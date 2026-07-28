import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.clients.question_service import TopicRef
from app.core.config import get_settings
from app.core.exceptions import UpstreamServiceError


@dataclass(frozen=True)
class BlueprintSlotSpec:
    topic_id: uuid.UUID
    weight: int
    difficulty_band: str
    difficulty_min: int
    difficulty_max: int
    question_count: int


@dataclass(frozen=True)
class BlueprintSpec:
    topic_mix: list[BlueprintSlotSpec]
    total_duration_minutes: int
    rationale: str


@dataclass(frozen=True)
class GenerationStatus:
    status: str
    question_id: uuid.UUID | None
    question_version_id: uuid.UUID | None
    error: str | None


class AiServiceClient(Protocol):
    """The exam service reaches the ai service over HTTP only (no code
    imports). Every call here happens inside some live, freshly-authenticated
    examiner request (schedule-ai, a later GET, confirm, or an override), so
    the caller's bearer token is always forwarded rather than minted fresh —
    same pattern as `question_service.py`'s examiner-plane calls."""

    async def propose_blueprint(
        self,
        *,
        authorization: str,
        candidate_profile_id: uuid.UUID,
        target_role: str,
        seniority_band: str,
        available_topics: list[TopicRef],
    ) -> BlueprintSpec: ...

    async def generate_question(
        self,
        *,
        authorization: str,
        topic_id: uuid.UUID,
        difficulty_band: str,
        language_targets: list[str],
    ) -> uuid.UUID: ...

    async def get_generation_status(
        self, *, authorization: str, job_id: uuid.UUID
    ) -> GenerationStatus: ...


class HttpAiServiceClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def propose_blueprint(
        self,
        *,
        authorization: str,
        candidate_profile_id: uuid.UUID,
        target_role: str,
        seniority_band: str,
        available_topics: list[TopicRef],
    ) -> BlueprintSpec:
        body = {
            "candidate_profile_id": str(candidate_profile_id),
            "target_role": target_role,
            "seniority_band": seniority_band,
            "available_topics": [{"id": str(t.id), "name": t.name} for t in available_topics],
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as client:
                response = await client.post(
                    "/blueprints/generate", json=body, headers={"Authorization": authorization}
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("AI service is unavailable") from exc
        if response.status_code != 200:
            raise UpstreamServiceError(f"AI service returned {response.status_code}")
        item = response.json()
        return BlueprintSpec(
            topic_mix=[
                BlueprintSlotSpec(
                    topic_id=uuid.UUID(slot["topic_id"]),
                    weight=slot["weight"],
                    difficulty_band=slot["difficulty_band"],
                    difficulty_min=slot["difficulty_min"],
                    difficulty_max=slot["difficulty_max"],
                    question_count=slot["question_count"],
                )
                for slot in item["topic_mix"]
            ],
            total_duration_minutes=item["total_duration_minutes"],
            rationale=item["rationale"],
        )

    async def generate_question(
        self,
        *,
        authorization: str,
        topic_id: uuid.UUID,
        difficulty_band: str,
        language_targets: list[str],
    ) -> uuid.UUID:
        body = {
            "topic_id": str(topic_id),
            "difficulty_band": difficulty_band,
            "language_targets": language_targets,
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.post(
                    "/questions/generate", json=body, headers={"Authorization": authorization}
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("AI service is unavailable") from exc
        if response.status_code != 201:
            raise UpstreamServiceError(f"AI service returned {response.status_code}")
        return uuid.UUID(response.json()["id"])

    async def get_generation_status(
        self, *, authorization: str, job_id: uuid.UUID
    ) -> GenerationStatus:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.get(
                    f"/questions/generate/{job_id}", headers={"Authorization": authorization}
                )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("AI service is unavailable") from exc
        if response.status_code != 200:
            raise UpstreamServiceError(f"AI service returned {response.status_code}")
        item = response.json()
        return GenerationStatus(
            status=item["status"],
            question_id=uuid.UUID(item["question_id"]) if item["question_id"] else None,
            question_version_id=(
                uuid.UUID(item["question_version_id"]) if item["question_version_id"] else None
            ),
            error=item["error"],
        )


def get_ai_client() -> AiServiceClient:
    # FastAPI dependency; overridden in tests with a fake.
    return HttpAiServiceClient(get_settings().ai_service_url)
