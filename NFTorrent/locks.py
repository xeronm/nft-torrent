import asyncio


class LockShouldWaitError(Exception):
    pass


class OperationLock:

    def __init__(self, key: str, lock_index: dict[str, asyncio.Lock], wait: bool = True):
        self.lock_index = lock_index
        self.key = key
        self.wait = wait

    async def __aenter__(self):
        self.lock = self.lock_index.get(self.key)
        if self.lock is None:
            self.lock = asyncio.Lock()
            self.lock.__ref_count = 0
            self.lock_index[self.key] = self.lock
        else:
            if not self.wait and self.lock.locked():
                raise LockShouldWaitError(f'Resource "{self.key}" locked, retry later')
        self.lock.__ref_count += 1
        await self.lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.lock.release()
        self.lock.__ref_count -= 1
        if self.lock.__ref_count == 0:
            del self.lock_index[self.key]
        self.lock = None

__all__ = ['OperationLock', 'LockShouldWaitError']