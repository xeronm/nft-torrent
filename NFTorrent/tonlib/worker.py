import asyncio
import logging
import logging.config
import multiprocessing as mp
import os
import queue
import random
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from pytonlib import BlockDeleted, BlockNotFound, TonlibClient, TonlibException

from NFTorrent.settings import TonlibSettings

from .models import TonlibClientResult, TonlibWorkerMsgType

logger = logging.getLogger(__name__)


class TonlibWorkerException(Exception):
    pass


class TonlibWorker(mp.Process):

    retry_timeout = 1
    sync_timeout = 90

    def __init__(
        self,
        ls_index: int,
        settings: TonlibSettings,
        input_queue: Optional[mp.Queue] = None,  # noqa: UP007
        output_queue: Optional[mp.Queue] = None,  # noqa: UP007
        sync_verify_address: str = None,
        logger_config: dict = None,
        keystore_recreate: bool = False,
        keystore_remove_on_fail: bool = True,
    ):
        super().__init__(daemon=True)

        self.input_queue = input_queue or mp.Queue()
        self.output_queue = output_queue or mp.Queue()
        self.exit_event = mp.Event()
        self.blockchain_failures = 0
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
        self.logger_config = logger_config
        self.keystore_recreate = keystore_recreate
        self.keystore_remove_on_fail = keystore_remove_on_fail

    def run(self):
        if self.logger_config:
            logging.config.dictConfig(self.logger_config)
        self.threadpool_executor = ThreadPoolExecutor(max_workers=16)

        policy = asyncio.get_event_loop_policy()
        policy.set_event_loop(policy.new_event_loop())
        self.loop = asyncio.new_event_loop()

        keystore = os.path.join(self.settings.keystore, f"ls_{self.ls_index:03d}")
        p = Path(keystore)
        if p.exists() and self.keystore_recreate:
            shutil.rmtree(keystore, ignore_errors=True)
        p.mkdir(parents=True, exist_ok=True)

        # init tonlib
        self.tonlib = TonlibClient(
            ls_index=self.ls_index,
            config=self.settings.liteserver_config,
            keystore=keystore,
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
        except Exception as E:
            logger.error(
                "TonlibWorker-#%03d: Failed to init and sync tonlib - %s: %s", self.ls_index, type(E).__name__, E
            )
            if p.exists() and self.keystore_remove_on_fail:
                shutil.rmtree(keystore, ignore_errors=True)
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

        if self.blockchain_failures:
            if p.exists() and self.keystore_remove_on_fail:
                shutil.rmtree(keystore, ignore_errors=True)

        self.shutdown(0 if self.exit_event.is_set() else 12)

    def shutdown(self, code: int):
        self.exit_event.set()
        for task in self.tasks.values():
            task.cancel()
        if self.tasks.values():
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
        logger.debug("TonlibWorker-#%03d: Synchronizing...", self.ls_index)
        result = None
        while result is None and not self.exit_event.is_set():
            try:
                result = await self.tonlib.sync_tonlib()
                last_block = result["seqno"]
                logger.warning(
                    "TonlibWorker-#%03d: Sync complete, workchain: %d, last_block: %d",
                    self.ls_index,
                    result["workchain"],
                    last_block,
                )
            except TonlibException as E:
                logger.info(
                    "TonlibWorker-#%03d: Initial sync timeout, Tonlib exception - %s: %s",
                    self.ls_index,
                    type(E).__name__,
                    E,
                )
                if time.monotonic() >= sync_mtimeout:
                    logger.error(
                        "TonlibWorker-#%03d: Initial sync timeout, last exception - %s: %s",
                        self.ls_index,
                        type(E).__name__,
                        E,
                    )
                    raise TonlibWorkerException("Initial sync timeout") from E
                await asyncio.sleep(self.retry_timeout)

    async def sync_verify(self):
        sync_mtimeout = time.monotonic() + self.sync_timeout
        logger.debug(
            "TonlibWorker-#%03d: Sync verifying... contract address: %s",
            self.ls_index,
            self.sync_verify_address,
        )
        result = None
        while result is None and not self.exit_event.is_set():
            try:
                result = await self.tonlib.generic_get_account_state(self.sync_verify_address)
                logger.warning(
                    "TonlibWorker-#%03d: Sync verify complete, address: %s, balance: %s, sync_time: %s",
                    self.ls_index,
                    self.sync_verify_address,
                    result["balance"],
                    time.ctime(result["sync_utime"]),
                )
            except TonlibException as E:
                logger.info(
                    "TonlibWorker-#%03d: Verify sync timeout, Tonlib exception - %s: %s",
                    self.ls_index,
                    type(E).__name__,
                    E,
                )
                if time.monotonic() >= sync_mtimeout:
                    logger.error(
                        "TonlibWorker-#%03d: Verify sync timeout, last exception - %s: %s",
                        self.ls_index,
                        type(E).__name__,
                        E,
                    )
                    raise TonlibWorkerException("Sync verify timeout") from E
                await asyncio.sleep(self.retry_timeout)

    async def report_sync(self):
        try:
            logger.debug("TonlibWorker-#%03d [report_sync]: entering main loop", self.ls_index)
            sync_mtimeout = time.monotonic() + self.sync_timeout
            while not self.exit_event.is_set():
                last_block = None
                try:
                    masterchain_info = await self.tonlib.get_masterchain_info()
                    last_block = masterchain_info["last"]["seqno"]
                    sync_mtimeout = time.monotonic() + self.sync_timeout
                except TonlibException as E:
                    logger.info(
                        "TonlibWorker-#%03d [report_sync]: Tonlib exception - %s: %s",
                        self.ls_index,
                        type(E).__name__,
                        E,
                    )
                    if time.monotonic() >= sync_mtimeout:
                        logger.error(
                            "TonlibWorker-#%03d [report_sync]: Loop sync timeout, last exception - %s: %s",
                            self.ls_index,
                            type(E).__name__,
                            E,
                        )
                        raise TonlibWorkerException("report_sync: Sync timeout") from E

                if last_block is not None:
                    self.last_block = last_block
                    await self.loop.run_in_executor(
                        self.threadpool_executor,
                        self.output_queue.put,
                        (TonlibWorkerMsgType.LAST_BLOCK_UPDATE, self.last_block),
                    )
                await asyncio.sleep(self.retry_timeout)
        except asyncio.CancelledError:
            logger.debug("TonlibWorker-#%03d [report_sync]: Task was cancelled", self.ls_index)
            return
        except TonlibWorkerException as E:
            logger.error(
                "TonlibWorker-#%03d [report_sync]: Task terminated with exception - %s: %s",
                self.ls_index,
                type(E).__name__,
                E,
            )
            raise
        except (Exception, BaseException):
            logger.exception(
                "TonlibWorker-#%03d [report_sync]: Task terminated with unhandled exception",
                self.ls_index,
            )
            raise

    async def report_archival(self):
        try:
            logger.debug("TonlibWorker-#%03d[report_archival]: entering main loop", self.ls_index)
            while not self.exit_event.is_set():
                try:
                    await self.tonlib.get_block_transactions(
                        -1, -9223372036854775808, random.randint(2, 4096), count=10
                    )
                    self.is_archival = True
                except BlockNotFound:
                    self.is_archival = False
                except TonlibException as E:
                    logger.error(
                        "TonlibWorker-#%03d [report_archival] Tonlib exception - %s: %s",
                        self.ls_index,
                        type(E).__name__,
                        E,
                    )

                await self.loop.run_in_executor(
                    self.threadpool_executor,
                    self.output_queue.put,
                    (TonlibWorkerMsgType.ARCHIVAL_UPDATE, self.is_archival),
                )
                await asyncio.sleep(600)
        except asyncio.CancelledError:
            logger.debug("TonlibWorker-#%03d [report_archival]: Task was cancelled", self.ls_index)
            return
        except (Exception, BaseException):
            logger.exception(
                "TonlibWorker-#%03d [report_archival]: Task terminated with unhandled exception",
                self.ls_index,
            )
            raise

    async def main_loop(self):
        logger.debug("TonlibWorker-#%03d [main_loop]: entering main loop", self.ls_index)
        try:
            while not self.exit_event.is_set():
                if self.blockchain_failures:
                    logger.info("TonlibWorker-#%03d [main_loop]: Loop exits due to blockchain failure", self.ls_index)
                    break

                try:
                    task_id, timeout, method, args, kwargs = await self.loop.run_in_executor(
                        self.threadpool_executor, self.input_queue.get, True, 1
                    )
                except queue.Empty:
                    continue

                self.loop.create_task(self.process_task(task_id, timeout, method, args, kwargs))
        except asyncio.CancelledError:
            logger.debug("TonlibWorker-#%03d [main_loop]: Task was cancelled", self.ls_index)
            return
        except (Exception, BaseException):
            logger.exception(
                "TonlibWorker-#%03d [main_loop]: Task terminated with unhandled exception",
                self.ls_index,
            )
            raise

    async def process_task(self, task_id, timeout, method, args, kwargs):
        result = None
        exception = None

        start_time = time.monotonic()
        if start_time < timeout:
            try:
                result = await self.tonlib.__getattribute__(method)(*args, **kwargs)
            except Exception as E:
                exception = E
                logger.warning(
                    "TonlibWorker-#%03d: Task '%s.%s' got exception - %s: %s",
                    self.ls_index,
                    task_id,
                    method,
                    type(E).__name__,
                    E,
                    extra={"method": method, "margs": args, "mkwargs": kwargs},
                )
                if isinstance(E, BlockDeleted):
                    self.blockchain_failures += 1
            else:
                logger.debug("TonlibWorker-#%03d: Task '%s.%s' got response", self.ls_index, task_id, method)
        else:
            exception = asyncio.TimeoutError()
            logger.warning("TonlibWorker-#%03d: Task '%s.%s' skipped by timeout", self.ls_index, task_id, method)
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
