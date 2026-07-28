"""Adaptive difficulty engine orchestration (Phase 2 Slice 5). See
docs/design-adaptive-difficulty.md. State is a single float per session,
held in Redis only (no Postgres row) — ephemeral, session-scoped, and
never meant to outlive an exam window."""

import uuid

from redis.asyncio import Redis

from app.core.redis_keys import difficulty_key
from app.difficulty.rules import (
    DEFAULT_DIFFICULTY,
    ComplexityHint,
    band_for_difficulty,
    compute_next_difficulty,
)

_STATE_TTL_SECONDS = 24 * 60 * 60


async def record_signal(
    redis: Redis,
    *,
    session_id: uuid.UUID,
    verdict: str,
    time_elapsed_pct: float,
    complexity_hint: ComplexityHint | None,
) -> tuple[float, str]:
    key = difficulty_key(session_id)
    raw = await redis.get(key)
    current = float(raw) if raw is not None else DEFAULT_DIFFICULTY

    next_difficulty = compute_next_difficulty(
        current,
        verdict=verdict,
        time_elapsed_pct=time_elapsed_pct,
        complexity_hint=complexity_hint,
    )
    await redis.set(key, str(next_difficulty), ex=_STATE_TTL_SECONDS)
    return next_difficulty, band_for_difficulty(next_difficulty)
