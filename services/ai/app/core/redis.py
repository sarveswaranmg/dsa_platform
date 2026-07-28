from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


def get_redis_client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def get_redis() -> Redis:
    # FastAPI dependency; overridden in tests to point at a throwaway DB index.
    return get_redis_client()


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None
