import asyncio
import sys
import time
import traceback
import subprocess
import multiprocessing as mp
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import queue
from .storage import TonStorageCliSettings, TonStorageCli
import logging
from dataclasses import dataclass
from typing import Dict, List

from loguru import logger

@dataclass
class WorkerCliTask:
    task_id: str
    timeout: float
    method: str
    args: List[any]
    kwargs: Dict[str, any]

@dataclass
class WorkerCliTaskResult:
    task_id: str
    result_time: float
    elapsed_time: float
    result: any
    exception: Exception = None

@dataclass
class WorkerStatusNotify:
    is_alive: bool
    peer_count: int
    date_time: float


class TonStorageCliWorker(mp.Process):
    report_state_interval = 10

    def __init__(self, 
                 client_id: int,
                 settings: TonStorageCliSettings, 
                 input_queue: Optional[mp.Queue] = None,
                 output_queue: Optional[mp.Queue] = None,
                 report_state_interval: int = None
                ):
        super().__init__(daemon=True)

        self.client_id = client_id
        self.settings = settings
        self.input_queue = input_queue or mp.Queue()
        self.output_queue = output_queue or mp.Queue()
        self.exit_event = mp.Event()
        self.threadpool_executor = None
        self.report_state_interval = report_state_interval or self.report_state_interval

    def run(self):
        self.threadpool_executor = ThreadPoolExecutor(max_workers=8)

        policy = asyncio.get_event_loop_policy()
        policy.set_event_loop(policy.new_event_loop())
        self.loop = asyncio.new_event_loop()

        # init cli
        self.cli = TonStorageCli(client_id=self.client_id, settings=self.settings)

        try:
            self.cli.open()
        except Exception as E:
            logger.error("TonStorageCliWorker #{client_id:03d}: failed to init: {exc}", client_id=self.client_id, exc=E)
            self.shutdown(11)

        # creating tasks
        self.tasks = {
            'main_loop': self.loop.create_task(self.main_loop()),
            'report_state': self.loop.create_task(self.report_state())            
        }

        finished, unfinished = self.loop.run_until_complete(asyncio.wait(self.tasks.values(), 
                                                            return_when=asyncio.FIRST_COMPLETED))

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
                try:
                    task = await self.loop.run_in_executor(self.threadpool_executor, self.input_queue.get, True, 1)
                except queue.Empty:
                    continue

                result = await self.loop.run_in_executor(None, self.process_task, task)

                await self.loop.run_in_executor(self.threadpool_executor, self.output_queue.put, result)
            except subprocess.CalledProcessError as E:
                logger.error("TonStorageCliWorker #{client_id:03d}: Subprocess error, output: {output}, {exc}", client_id=self.client_id, output=E.output, exc=str(E))
                self.shutdown(10)
            except Exception as E:
                logger.error("TonStorageCliWorker #{client_id:03d}: Unhandled exception: {exc}", client_id=self.client_id, exc=traceback.format_exc())
                raise

    async def report_state(self):
        while not self.exit_event.is_set():
            try:
                is_alive, peer_count = await self.loop.run_in_executor(None, self.request_state)
                logger.debug("TonStorageCliWorker #{client_id:03d}: status notify is_alive: {is_alive}, peer_count: {peer_count}", 
                            client_id=self.client_id, is_alive=is_alive, peer_count=peer_count)
                await self.loop.run_in_executor(self.threadpool_executor, self.output_queue.put, 
                                                WorkerStatusNotify(is_alive, peer_count, time.time())
                                                )

                await asyncio.sleep(self.report_state_interval)
            except subprocess.CalledProcessError as E:
                logger.error("TonStorageCliWorker #{client_id:03d}: Subprocess error, output: {output}, {exc}", client_id=self.client_id, output=E.output, exc=str(E))
                self.shutdown(10)
            except Exception as E:
                logger.error("TonStorageCliWorker #{client_id:03d}: Unhandled exception: {exc}", client_id=self.client_id, exc=traceback.format_exc())
                raise                

    def request_state(self):
        peers = self.cli.node_get_state()
        peer_count = 0
        if isinstance(peers, list):
            peer_count = len(peers)
        return self.cli.is_alive(), peer_count

    def process_task(self, task: WorkerCliTask):
        result = None
        exception = None

        start_time = time.monotonic()
        if start_time < task.timeout:
            try:
                result = self.cli.__getattribute__(task.method)(*task.args, **task.kwargs)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as E: 
                exception = E
                logger.warning("TonStorageCliWorker #{client_id:03d}: Got exception, method: {method}, task_id: {task_id}, args: {args}, kwargs: {kwargs}, exception: {exc}", 
                               client_id=self.client_id, method=task.method, task_id=task.task_id, args=task.args, kwargs=task.kwargs, exc=str(E))
            except Exception as E:
                exception = E
                logger.warning("TonStorageCliWorker #{client_id:03d}: Got unhandled exception, method: {method}, task_id: {task_id}, args: {args}, kwargs: {kwargs}, exception: {exc}", 
                               client_id=self.client_id, method=task.method, task_id=task.task_id, args=task.args, kwargs=task.kwargs, exc=E)
            else:
                logger.debug("TonStorageCliWorker #{client_id:03d}: Got result, method: {method}, task \"{task_id}\"", 
                             client_id=self.client_id, method=task.method, task_id=task.task_id)
        else:
            exception = asyncio.TimeoutError()
            logger.warning("TonStorageCliWorker #{client_id:03d}: Received task after timeout, method: {method}, task_id: {task_id}",
                            client_id=self.client_id, method=task.method, task_id=task.task_id)
        end_time = time.monotonic()
        elapsed_time = end_time - start_time

        return WorkerCliTaskResult(task.task_id, end_time, elapsed_time, result, exception)
