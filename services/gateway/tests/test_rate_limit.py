from unittest.mock import AsyncMock

from app.auth import Identity
from app.rate_limit import RedisRateLimiter


async def test_check_builds_a_prefixed_key() -> None:
    redis = AsyncMock()
    redis.incr.return_value = 1
    limiter = RedisRateLimiter(redis)
    identity = Identity(kind="examiner", value="sub-1")

    await limiter.check(identity, limit=10)

    incr_key = redis.incr.await_args.args[0]
    expire_key = redis.expire.await_args.args[0]
    assert incr_key == expire_key
    assert incr_key.startswith("gw:rl:examiner:sub-1:")


async def test_check_never_builds_an_unprefixed_key() -> None:
    redis = AsyncMock()
    redis.incr.return_value = 1
    limiter = RedisRateLimiter(redis)
    identity = Identity(kind="ip", value="203.0.113.1")

    await limiter.check(identity, limit=10)

    key = redis.incr.await_args.args[0]
    assert key.startswith("gw:")
    assert not key.startswith("rl:")
