import redis.asyncio as aioredis

from app.config import settings

STREAM = "katlego:inbound"
GROUP = "workers"

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        # socket_timeout must exceed the worker's XREADGROUP block (5s) or the
        # client raises TimeoutError on idle blocking reads (seen on redis-py 8.x).
        _redis = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=30
        )
    return _redis


async def ensure_group() -> None:
    r = get_redis()
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
