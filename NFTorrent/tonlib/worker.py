import asyncio
import random
import sys
import time
import queue
import traceback
import multiprocessing as mp

from pytonlib import TonlibClient, TonlibException, BlockNotFound
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from typing import Optional

from NFTorrent.settings import TonlibSettings
from .models import TonlibWorkerMsgType, TonlibClientResult

from loguru import logger


class TonlibWorkerException(Exception):
    pass


class TonlibWorker(mp.Process):

    retry_timeout = 1
    sync_timeout = 30

    def __init__(
        self,
        ls_index: int,
        settings: TonlibSettings,
        input_queue: Optional[mp.Queue] = None,
        output_queue: Optional[mp.Queue] = None,
        sync_verify_address: str = None,
    ):
        super(TonlibWorker, self).__init__(daemon=True)

        self.input_queue = input_queue or mp.Queue()
        self.output_queue = output_queue or mp.Queue()
        self.exit_event = mp.Event()
        self.sync_verify_address = sync_verify_address

        self.ls_index = ls_index
        self.settings = settings

        self.last_block = -1
        self.is_archival = False
        self.loop = None
        self.tasks = {}
        self.tonlib = None
        self.threadpool_executor = None
        self.sync_timeout = max(self.sync_timeout, self.settings.request_timeout)

    def run(self):
        self.threadpool_executor = ThreadPoolExecutor(max_workers=16)

        policy = asyncio.get_event_loop_policy()
        policy.set_event_loop(policy.new_event_loop())
        self.loop = asyncio.new_event_loop()

        Path(self.settings.keystore).mkdir(parents=True, exist_ok=True)

        # init tonlib
        self.tonlib = TonlibClient(
            ls_index=self.ls_index,
            config=self.settings.liteserver_config,
            keystore=self.settings.keystore,
            loop=self.loop,
            cdll_path=self.settings.cdll_path,
            verbosity_level=self.settings.verbosity_level,
            tonlib_timeout=self.settings.request_timeout,
        )

        try:
            self.loop.run_until_complete(self.tonlib.init())
            self.loop.run_until_complete(self.sync_initial())
            if self.sync_verify_address:
                self.loop.run_until_complete(self.sync_verify())
        except Exception as e:
            logger.error(
                "TonlibWorker #{ls_index:03d} failed to init and sync tonlib: {exc}", ls_index=self.ls_index, exc=e
            )
            self.shutdown(11)

        # creating tasks
        self.tasks = {
            "report_sync": self.loop.create_task(self.report_sync()),
            "report_archival": self.loop.create_task(self.report_archival()),
            "main_loop": self.loop.create_task(self.main_loop()),
        }

        finished, unfinished = self.loop.run_until_complete(
            asyncio.wait(self.tasks.values(), return_when=asyncio.FIRST_COMPLETED)
        )

        self.shutdown(0 if self.exit_event.is_set() else 12)

    def shutdown(self, code: int):
        self.exit_event.set()
        for task in self.tasks.values():
            task.cancel()
        self.loop.run_until_complete(asyncio.wait(self.tasks.values(), return_when=asyncio.ALL_COMPLETED))

        self.threadpool_executor.shutdown()

        self.output_queue.cancel_join_thread()
        self.input_queue.cancel_join_thread()
        self.output_queue.close()
        self.input_queue.close()
        sys.exit(code)

    @property
    def info(self):
        return {
            "ip_int": f"{self.settings.liteserver_config['liteservers'][self.ls_index]['ip']}",
            "port": f"{self.settings.liteserver_config['liteservers'][self.ls_index]['port']}",
            "last_block": self.last_block,
            "archival": self.is_archival,
            "number": self.ls_index,
        }

    async def sync_initial(self):
        sync_mtimeout = time.monotonic() + self.sync_timeout
        logger.debug("TonlibWorker #{ls_index:03d}: synchronizing...", ls_index=self.ls_index)
        result = None
        while result is None and not self.exit_event.is_set():
            try:
                result = await self.tonlib.sync_tonlib()
                last_block = result["seqno"]
                logger.warning(
                    "TonlibWorker #{ls_index:03d}: sync complete, workchain: {workchain}, last_block: {last_block}",
                    ls_index=self.ls_index,
                    workchain=result["workchain"],
                    last_block=last_block,
                )
            except TonlibException as E:
                logger.info(
                    "TonlibWorker #{ls_index:03d}: TonlibException, {exc}",
                    ls_index=self.ls_index,
                    exc=E,
                )
                if time.monotonic() >= sync_mtimeout:
                    logger.error(
                        "TonlibWorker #{ls_index:03d}: Initial sync timeout, last exception of type {exc_type}: {exc}",
                        ls_index=self.ls_index,
                        exc_type=type(E).__name__,
                        exc=E,
                    )
                    raise TonlibWorkerException("Initial sync timeout") from E
                await asyncio.sleep(self.retry_timeout)

    async def sync_verify(self):
        sync_mtimeout = time.monotonic() + self.sync_timeout
        logger.debug(
            "TonlibWorker #{ls_index:03d}: sync verifying... {address}",
            ls_index=self.ls_index,
            address=self.sync_verify_address,
        )
        result = None
        while result is None and not self.exit_event.is_set():
            try:
                result = await self.tonlib.generic_get_account_state(self.sync_verify_address)
                logger.warning(
                    "TonlibWorker #{ls_index:03d}: sync verify complete, address: {address}, balance: {balance}, sync_time: {sync_time}",
                    ls_index=self.ls_index,
                    address=self.sync_verify_address,
                    balance=result["balance"],
                    sync_time=time.ctime(result["sync_utime"])
                )
            except TonlibException as E:
                logger.info(
                    "TonlibWorker #{ls_index:03d}: TonlibException, {exc}",
                    ls_index=self.ls_index,
                    exc=E,
                )
                if time.monotonic() >= sync_mtimeout:
                    logger.error(
                        "TonlibWorker #{ls_index:03d}: Verify sync timeout, last exception of type {exc_type}: {exc}",
                        ls_index=self.ls_index,
                        exc_type=type(E).__name__,
                        exc=E,
                    )
                    raise TonlibWorkerException("Sync verify timeout") from E
                await asyncio.sleep(self.retry_timeout)

    async def report_sync(self):
        try:
            logger.debug("TonlibWorker #{ls_index:03d}[report_sync]: entering main loop", ls_index=self.ls_index)
            sync_mtimeout = time.monotonic() + self.sync_timeout
            while not self.exit_event.is_set():
                last_block = None
                try:
                    masterchain_info = await self.tonlib.get_masterchain_info()
                    last_block = masterchain_info["last"]["seqno"]
                    sync_mtimeout = time.monotonic() + self.sync_timeout
                except TonlibException as E:
                    logger.info(
                        "TonlibWorker #{ls_index:03d}[report_sync]: Tonlib exception of type {exc_type}: {exc}",
                        ls_index=self.ls_index,
                        exc_type=type(E).__name__,
                        exc=E,
                    )
                    if time.monotonic() >= sync_mtimeout:
                        logger.error(
                            "TonlibWorker #{ls_index:03d}[report_sync]: Loop sync timeout, last exception of type {exc_type}: {exc}",
                            ls_index=self.ls_index,
                            exc_type=type(E).__name__,
                            exc=E,
                        )
                        raise TonlibWorkerException("report_sync: loop sync timeout") from E

                if last_block is not None:
                    self.last_block = last_block
                    await self.loop.run_in_executor(
                        self.threadpool_executor,
                        self.output_queue.put,
                        (TonlibWorkerMsgType.LAST_BLOCK_UPDATE, self.last_block),
                    )
                await asyncio.sleep(self.retry_timeout)
        except asyncio.CancelledError:
            logger.debug("TonlibWorker #{ls_index:03d}[report_sync]: Task was cancelled", ls_index=self.ls_index)
            return
        except TonlibWorkerException as E:
            logger.error(
                "TonlibWorker #{ls_index:03d}[report_sync]: Task terminated with exception of type {exc_type}: {exc}",
                ls_index=self.ls_index,
                exc_type=type(E).__name__,
                exc=E,
            )
            raise
        except (Exception, BaseException):
            logger.critical(
                "TonlibWorker #{ls_index:03d}[report_sync]: Task terminated with unhandled exception: {exc}",
                ls_index=self.ls_index,
                exc=traceback.format_exc(),
            )
            raise

    async def report_archival(self):
        try:
            logger.debug("TonlibWorker #{ls_index:03d}[report_archival]: entering main loop", ls_index=self.ls_index)
            while not self.exit_event.is_set():
                try:
                    block_transactions = await self.tonlib.get_block_transactions(
                        -1, -9223372036854775808, random.randint(2, 4096), count=10
                    )
                    self.is_archival = True
                except BlockNotFound as e:
                    self.is_archival = False
                except TonlibException as e:
                    logger.error(
                        "TonlibWorker #{ls_index:03d}[report_archival] exception of type {exc_type}: {exc}",
                        ls_index=self.ls_index,
                        exc_type=type(e).__name__,
                        exc=e,
                    )

                await self.loop.run_in_executor(
                    self.threadpool_executor,
                    self.output_queue.put,
                    (TonlibWorkerMsgType.ARCHIVAL_UPDATE, self.is_archival),
                )
                await asyncio.sleep(600)
        except asyncio.CancelledError:
            logger.debug("TonlibWorker #{ls_index:03d}[report_archival]: Task was cancelled", ls_index=self.ls_index)
            return

    async def main_loop(self):
        logger.debug("TonlibWorker #{ls_index:03d}[main_loop]: entering main loop", ls_index=self.ls_index)
        while not self.exit_event.is_set():
            try:
                try:
                    task_id, timeout, method, args, kwargs = await self.loop.run_in_executor(
                        self.threadpool_executor, self.input_queue.get, True, 1
                    )
                except queue.Empty:
                    continue

                self.loop.create_task(self.process_task(task_id, timeout, method, args, kwargs))
            except asyncio.CancelledError:
                logger.debug("TonlibWorker #{ls_index:03d}[main_loop]: Task was cancelled", ls_index=self.ls_index)
                return
            except (Exception, BaseException):
                logger.critical(
                    "TonlibWorker #{ls_index:03d}[main_loop]: Task terminated with unhandled exception: {exc}",
                    ls_index=self.ls_index,
                    exc=traceback.format_exc(),
                )
                raise

    async def process_task(self, task_id, timeout, method, args, kwargs):
        result = None
        exception = None

        start_time = time.monotonic()
        if start_time < timeout:
            try:
                result = await self.tonlib.__getattribute__(method)(*args, **kwargs)
            except Exception as e:
                exception = e
                logger.warning(
                    "TonlibWorker #{ls_index:03d}: raised exception of type {exc_type} while executing task. Method: {method}, args: {args}, kwargs: {kwargs}, exception: {exc}",
                    ls_index=self.ls_index,
                    method=method,
                    args=args,
                    kwargs=kwargs,
                    exc_type=type(e).__name__,
                    exc=e,
                )
            else:
                logger.debug(
                    "TonlibWorker #{ls_index:03d}: got result {method} for task '{task_id}'",
                    ls_index=self.ls_index,
                    method=method,
                    task_id=task_id,
                )
        else:
            exception = asyncio.TimeoutError()
            logger.warning(
                "TonlibWorker #{ls_index:03d}: received task '{task_id}' after timeout",
                ls_index=self.ls_index,
                task_id=task_id,
            )
        end_time = time.monotonic()
        elapsed_time = end_time - start_time

        # result
        tonlib_task_result = TonlibClientResult(
            task_id,
            method,
            elapsed_time=elapsed_time,
            params=[args, kwargs],
            result=result,
            exception=exception,
            liteserver_info=self.info,
        )
        await self.loop.run_in_executor(
            self.threadpool_executor, self.output_queue.put, (TonlibWorkerMsgType.TASK_RESULT, tonlib_task_result)
        )
