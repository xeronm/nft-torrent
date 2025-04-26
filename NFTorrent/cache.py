import redis.asyncio
import ring
from loguru import logger
from pyTON.settings import RedisCacheSettings
from ring.func.asyncio import Aioredis2Storage


class ResultRedisStorage(Aioredis2Storage):
    async def set(self, key, value, expire=...):
        if isinstance(value, dict) and value.get('@type', 'error') == 'error':
            return None
        return await super().set(key, value, expire)


class RedisCacheManager:
    def __init__(self, cache_settings: RedisCacheSettings):
        self.cache_settings = cache_settings
        redis_url = f"redis://{cache_settings.redis.endpoint}:{cache_settings.redis.port}"
        logger.warning("Redis Cache: {redis_url}", redis_url=redis_url)
        self.cache_redis = redis.asyncio.from_url(redis_url,
                                                  socket_timeout=cache_settings.redis.timeout,
                                                  socket_connect_timeout=cache_settings.redis.timeout,
                                                  socket_keepalive=True)

    def cached(self, expire=0, check_error=True):
        storage_class = ResultRedisStorage if check_error else Aioredis2Storage

        def g(func):
            return ring.aioredis(self.cache_redis, coder='pickle', expire=expire, storage_class=storage_class)(func)

        return g
