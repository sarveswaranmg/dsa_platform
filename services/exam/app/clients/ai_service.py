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


@dataclass(frozen=True)
class DifficultySignal:
    difficulty: float
    difficulty_band: str


@dataclass(frozen=True)
class FollowupFactoryResult:
    status: str


class AiServiceClient(Protocol):
    """The exam service reaches the ai service over HTTP only (no code
    imports). Examiner-plane calls (`propose_blueprint`, `generate_question`,
    `get_generation_status`) happen inside some live, freshly-authenticated
    examiner request, so the caller's bearer token is forwarded rather than
    minted fresh. `send_difficulty_signal` is different: it's called from the
    detached verdict-consumer background loop, which has no live token to
    forward, so it hits an unauthenticated `/internal/...` route instead —
    same split `question_service.py` already has between its examiner-plane
    and internal/candidate-plane methods."""

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

    async def send_difficulty_signal(
        self,
        *,
        session_id: uuid.UUID,
        question_version_id: uuid.UUID,
        time_elapsed_pct: float,
        verdict: str,
        complexity_hint: str | None,
    ) -> DifficultySignal: ...

    async def run_followup_factory(
        self,
        *,
        org_id: uuid.UUID,
        question_version_id: uuid.UUID,
        source_question_id: uuid.UUID,
    ) -> FollowupFactoryResult: ...


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

    async def send_difficulty_signal(
        self,
        *,
        session_id: uuid.UUID,
        question_version_id: uuid.UUID,
        time_elapsed_pct: float,
        verdict: str,
        complexity_hint: str | None,
    ) -> DifficultySignal:
        body = {
            "session_id": str(session_id),
            "question_version_id": str(question_version_id),
            "time_elapsed_pct": time_elapsed_pct,
            "verdict": verdict,
            "complexity_hint": complexity_hint,
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=10.0) as client:
                response = await client.post("/internal/difficulty/signal", json=body)
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("AI service is unavailable") from exc
        if response.status_code != 200:
            raise UpstreamServiceError(f"AI service returned {response.status_code}")
        item = response.json()
        return DifficultySignal(
            difficulty=item["difficulty"], difficulty_band=item["difficulty_band"]
        )

    async def run_followup_factory(
        self,
        *,
        org_id: uuid.UUID,
        question_version_id: uuid.UUID,
        source_question_id: uuid.UUID,
    ) -> FollowupFactoryResult:
        # No authorization param (internal/unauthenticated) — a proctor's
        # follow-up has no ADMIN/AUTHOR token to forward to the examiner-facing
        # POST /test-cases/generate. Always runs synchronously (~30s budget)
        # since the result must be attached before the version is published.
        body = {
            "org_id": str(org_id),
            "question_version_id": str(question_version_id),
            "source_question_id": str(source_question_id),
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=35.0) as client:
                response = await client.post("/internal/test-cases/generate", json=body)
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("AI service is unavailable") from exc
        if response.status_code != 201:
            raise UpstreamServiceError(f"AI service returned {response.status_code}")
        return FollowupFactoryResult(status=response.json()["status"])


def get_ai_client() -> AiServiceClient:
    # FastAPI dependency; overridden in tests with a fake.
    return HttpAiServiceClient(get_settings().ai_service_url)
