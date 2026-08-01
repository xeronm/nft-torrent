import asyncio
import time


class RateLimitBase:

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        await self.release()


class TokenBucketRateLimit(RateLimitBase):

    def __init__(self, rate_limit: int, burst_size: int = None, max_pending: int = None):
        self.rate_limit = rate_limit
        self.burst_size = burst_size or max(rate_limit, 1)
        self._lock = asyncio.Lock()
        self._pending = asyncio.Semaphore(max_pending or self.burst_size)
        self._tokens = self.burst_size
        self._last_refill = time.monotonic()

    def _refill(self):
        now_ts = time.monotonic()
        elapsed = now_ts - self._last_refill
        self._tokens = min(self.burst_size, self._tokens + elapsed * self.rate_limit)
        self._last_refill = now_ts

    async def acquire(self):
        await self._pending.acquire()
        async with self._lock:
            self._refill()
            while self._tokens < 1:
                wait_time = (1 - self._tokens) / self.rate_limit
                await asyncio.sleep(wait_time)
                self._refill()
            self._tokens -= 1

    async def release(self):
        self._pending.release()


class UniformRateLimit(RateLimitBase):

    def __init__(self, rate_limit: int, max_pending: int = None):
        self._interval = 1.0 / rate_limit
        self._lock = asyncio.Lock()
        self._pending = asyncio.Semaphore(max_pending or max(rate_limit, 1))
        self._delay_until = time.monotonic()

    async def acquire(self):
        await self._pending.acquire()
        async with self._lock:
            now_ts = time.monotonic()
            timeout = self._delay_until - now_ts
            if timeout > 0:
                await asyncio.sleep(timeout)
                now_ts = time.monotonic()

            self._delay_until = now_ts + self._interval

    async def release(self):
        self._pending.release()
        self._delay_until = time.monotonic() + self._interval
