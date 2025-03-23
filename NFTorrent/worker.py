import asyncio
import sys
import time
import multiprocessing as mp
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import queue
from .storage import TonStorageCliSettings, TonStorageCli
import logging

logger = logging.getLogger(__name__)

class TonStorageCliWorker(mp.Process):

    def __init__(self, 
                 client_id: int,
                 settings: TonStorageCliSettings, 
                 input_queue: Optional[mp.Queue]=None,
                 output_queue: Optional[mp.Queue]=None):
        super().__init__(daemon=True)

        self.client_id = client_id
        self.settings = settings
        self.input_queue = input_queue or mp.Queue()
        self.output_queue = output_queue or mp.Queue()
        self.exit_event = mp.Event()

        self.threadpool_executor = None

        self.is_dead = False

    def run(self):
        self.threadpool_executor = ThreadPoolExecutor(max_workers=8)

        policy = asyncio.get_event_loop_policy()
        policy.set_event_loop(policy.new_event_loop())
        self.loop = asyncio.new_event_loop()

        # init cli
        self.cli = TonStorageCli(client_id=self.client_id, settings=self.settings)

        try:
            self.loop.run_until_complete(self.cli.open())
        except Exception as E:
            logger.error('TonStorageCliWorker #%03d: failed to init and sync tonlib: %s', self.client_id, E)
            self.shutdown(11)

        # creating tasks
        self.tasks['main_loop'] = self.loop.create_task(self.main_loop())
        self.tasks['lru_cleanup'] = self.loop.create_task(self.lru_cleanup())
        self.tasks['indexer'] = self.loop.create_task(self.indexer())

        finished, unfinished = self.loop.run_until_complete(asyncio.wait(self.tasks.values()), 
                                                            return_when=asyncio.FIRST_COMPLETED)

        self.shutdown(0 if self.exit_event.is_set() else 12)

    def shutdown(self, code: int):
        self.exit_event.set()
        self.threadpool_executor.shutdown()

        self.output_queue.cancel_join_thread()
        self.input_queue.cancel_join_thread()
        self.output_queue.close()
        self.input_queue.close()
        sys.exit(code)

    async def main_loop(self):
        while not self.exit_event.is_set():
            try:
                task_id, timeout, method, args, kwargs = await self.loop.run_in_executor(self.threadpool_executor, self.input_queue.get, True, 1)
            except queue.Empty:
                continue

            self.loop.create_task(self.process_task(task_id, timeout, method, args, kwargs))        

    async def lru_cleanup(self):
        while not self.exit_event.is_set():
            await asyncio.sleep(0.5)

    async def indexer(self):
        while not self.exit_event.is_set():
            await asyncio.sleep(0.5)

    async def process_task(self, task_id, timeout, method, args, kwargs):
        result = None
        exception = None

        start_time = time.monotonic()
        if start_time < timeout:
            try:
                result = await self.cli.__getattribute__(method)(*args, **kwargs)
            except Exception as E:
                exception = E
                logger.warning(f'TonStorageCliWorker #{self.client_id:03d}: unhandled exception. Method: {method}, args: {args}, kwargs: {kwargs}, exception: {E}')
            else:
                logger.debug(f'TonStorageCliWorker #{self.client_id:03d}: got result {method} for task "{task_id}"')
        else:
            exception = asyncio.TimeoutError()
            logger.warning(f'TonStorageCliWorker #{self.client_id:03d}: received task "{task_id}" after timeout')
        end_time = time.monotonic()
        elapsed_time = (end_time - start_time).total_seconds()

        await self.loop.run_in_executor(self.threadpool_executor, self.output_queue.put, (task_id, elapsed_time, result, exception))