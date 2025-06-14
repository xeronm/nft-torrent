import redis.asyncio
import ring
from ring.func.asyncio import Aioredis2Storage

from NFTorrent.settings import BaseCacheManager, MemoryCacheSettings, RedisCacheSettings


class DisabledCacheManager(BaseCacheManager):
    settings_class = None

    def cached(self, expire=0, check_error=True):
        def g(func):
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return g


class ResultRedisStorage(Aioredis2Storage):
    async def set(self, key, value, expire=...):
        if isinstance(value, dict) and value.get("@type", "error") == "error":
            return None
        return await super().set(key, value, expire)


class RedisCacheManager(BaseCacheManager):
    settings_class = RedisCacheSettings

    def __init__(self, cache_settings: RedisCacheSettings):
        self.cache_settings = cache_settings
        redis_url = f"redis://{cache_settings.endpoint}:{cache_settings.port}"
        self.cache_redis = redis.asyncio.from_url(
            redis_url,
            socket_timeout=cache_settings.timeout,
            socket_connect_timeout=cache_settings.timeout,
            socket_keepalive=True,
        )

    def cached(self, expire=0, check_error=True):
        storage_class = ResultRedisStorage if check_error else Aioredis2Storage

        def g(func):
            return ring.aioredis(self.cache_redis, coder="pickle", expire=expire, storage_class=storage_class)(func)

        return g


class MemoryCacheManager(BaseCacheManager):
    settings_class = MemoryCacheSettings

    def __init__(self, cache_settings: MemoryCacheSettings):
        self.cache_settings = cache_settings

    def cached(self, expire=0, check_error=True):
        def decorator(func):
            return ring.lru(expire=expire, maxsize=self.cache_settings.max_size, force_asyncio=True)(func)

        return decorator
