"""Per-identity fixed-window rate limiting backed by Redis.

Redis (not process memory) so the budget is shared across gateway replicas —
the same reason session state lives there.
"""

import time
from typing import Protocol

from redis.asyncio import Redis

from app.auth import Identity
from app.config import get_settings


class RateLimiter(Protocol):
    async def check(self, identity: Identity, limit: int) -> int | None:
        """Return None when allowed, else seconds to wait (Retry-After)."""
        ...


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(self, identity: Identity, limit: int) -> int | None:
        window = get_settings().rate_limit_window_seconds
        bucket = int(time.time()) // window
        key = f"gw:rl:{identity}:{bucket}"

        count = await self._redis.incr(key)
        if count == 1:
            # Only the first writer in a window sets the TTL, so the window
            # cannot be extended by later requests.
            await self._redis.expire(key, window)
        if count > limit:
            return window - (int(time.time()) % window)
        return None


class AllowAllRateLimiter:
    """Used when Redis is unavailable in tests."""

    async def check(self, identity: Identity, limit: int) -> int | None:
        return None
