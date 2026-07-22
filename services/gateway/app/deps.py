"""Shared dependencies, injectable so tests supply fakes (no real upstreams
or Redis needed)."""

import httpx
from redis.asyncio import Redis

from app.config import get_settings
from app.proxy import Forwarder, HttpForwarder
from app.rate_limit import RateLimiter, RedisRateLimiter

_client: httpx.AsyncClient | None = None
_redis: Redis | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=get_settings().upstream_timeout_seconds)
    return _client


def get_redis_client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def get_forwarder() -> Forwarder:
    return HttpForwarder(get_http_client())


def get_rate_limiter() -> RateLimiter:
    return RedisRateLimiter(get_redis_client())


async def shutdown() -> None:
    global _client, _redis
    if _client is not None:
        await _client.aclose()
    if _redis is not None:
        await _redis.aclose()
    _client = None
    _redis = None
