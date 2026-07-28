from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.core.redis import get_redis
from app.schemas.difficulty import DifficultySignalRequest, DifficultySignalResponse
from app.services import difficulty as difficulty_service

# Unauthenticated (trusted-network-only), same convention as this service's
# other /internal/... routes — the caller is exam's detached verdict-consumer
# background loop, which has no live bearer token to forward. Blocked at the
# gateway edge (services/gateway/app/routing.py: Route("/internal", ...)).
router = APIRouter(prefix="/internal/difficulty", tags=["internal"])

RedisDep = Annotated[Redis, Depends(get_redis)]


@router.post("/signal", response_model=DifficultySignalResponse)
async def signal(
    body: DifficultySignalRequest, redis: RedisDep
) -> DifficultySignalResponse:
    difficulty, band = await difficulty_service.record_signal(
        redis,
        session_id=body.session_id,
        verdict=body.verdict,
        time_elapsed_pct=body.time_elapsed_pct,
        complexity_hint=body.complexity_hint,
    )
    return DifficultySignalResponse(difficulty=difficulty, difficulty_band=band)
