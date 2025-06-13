import asyncio
import random
import time
import os
from datetime import datetime
import queue
import traceback
from dataclasses import dataclass, InitVar, asdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any
from collections.abc import Mapping

from loguru import logger
from pytonlib import TonlibError
from pytonlib.utils.tokens import parse_nft_collection_data, parse_nft_item_data
from tonpy.types import CellSlice

from NFTorrent.modelsbase import (
    CollectionConfig,
    CollectionData,
    MeasurementStore,
    NftItemData,
    StatisticMeasurement,
    TonAddress,
    dataclass_to_influx
)
from NFTorrent.settings import TonlibSettings, BaseCacheManager
from NFTorrent.cache import DisabledCacheManager

from .worker import TonlibWorker
from .models import TonlibWorkerMsgType, TonlibClientResult


class TonlibRequestError(Exception):
    pass


@dataclass(frozen=True)
class StatisticTags:
    ls_index: str
    method: str


@dataclass
class WorkerControl:
    _worker: InitVar[TonlibWorker]
    _reader: InitVar[asyncio.Task]
    _futures: InitVar[dict[str, Any]] = None
    ls_index: int = 0
    config: dict[str, Any] = None
    is_alive: bool = False
    is_sync: bool = False
    is_enabled: bool = True
    is_archival: bool = False
    last_block: int = -1
    last_block_time: float = 0
    start_mt: float = 0
    start_time: float = 0
    restart_count: int = 0
    tasks_count: int = 0
    pending_tasks: int = 0
    sync_time: float = 0
    sync_mt: float = 0
    sync_duration: int = 0
    sync_dur_ema: float = 0
    off_sync_time: float = 0
    off_sync_mt: float = 0
    off_sync_count: int = 0
    off_sync_duration: int = 0
    off_sync_dur_ema: float = 0

    def __post_init__(self, worker: TonlibWorker, reader: asyncio.Task, futures: dict[str, Any] = None):
        self._worker = worker
        self._reader = reader
        self.ls_index = worker.ls_index
        self.config = worker.tonlib.local_config
        self._futures = futures or {}

    @property
    def futures(self) -> dict[str, Any]:
        return self._futures

    @property
    def worker(self) -> TonlibWorker:
        return self._worker

    @property
    def reader(self) -> asyncio.Task:
        return self._reader

    def set_worker(self, worker: TonlibWorker, reader: asyncio.Task):
        if worker.ls_index != self.ls_index:
            raise RuntimeError('Invalid usage, "ls_index" mistmatch')
        self._worker = worker
        self._reader = reader


class TonlibManager:
    ema_alpha = 0.1

    def __init__(
        self,
        settings: TonlibSettings,
        restart_timeout: int = None,
        cache_manager: BaseCacheManager = None,
        loop: asyncio.BaseEventLoop = None,
        collection_config: CollectionConfig = None,
    ):
        self.restart_timeout = restart_timeout or settings.restart_timeout
        self.collection_config = collection_config
        self.stats = MeasurementStore("NFTorrentLiteserver", StatisticMeasurement)
        self.settings = settings
        self.cache_manager = cache_manager or DisabledCacheManager()

        self.workers: dict[int, WorkerControl] = {}
        self.tasks = {}
        self.consensus_block = -1
        self.consensus_block_mt = 0

        # cache setup
        self.setup_cache()

        liteservers_num = len(self.settings.liteserver_config["liteservers"])
        workers_num = min(liteservers_num, self.settings.max_liteservers)
        logger.info(
            "TonlibManager: workers count: {workers_num}, liteservers count: {liteservers_num}",
            workers_num=workers_num,
            liteservers_num=liteservers_num,
        )
        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, workers_num * 4))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        for ls_index in range(workers_num):
            self.spawn_worker(ls_index)

        # running tasks
        self.tasks["check_working"] = self.loop.create_task(self.check_working())
        self.tasks["check_children_alive"] = self.loop.create_task(self.check_children_alive())

    async def shutdown(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.wait(self.tasks.values())
        await asyncio.wait([self.loop.create_task(self.worker_control(i, enabled=False)) for i in self.workers])
        self.threadpool_executor.shutdown()

    def setup_cache(self):
        # short-term
        self.raw_run_method = self.cache_manager.cached(expire=5)(self.raw_run_method)
        # mid-term
        self.raw_get_account_state = self.cache_manager.cached(expire=15)(self.raw_get_account_state)
        self.generic_get_account_state = self.cache_manager.cached(expire=15)(self.generic_get_account_state)
        self.get_nft_data = self.cache_manager.cached(expire=60)(self.get_nft_data)
        self.get_collection_data = self.cache_manager.cached(expire=60)(self.get_collection_data)
        # long-term
        self.get_nft_item_address = self.cache_manager.cached(expire=600)(self.get_nft_item_address)

    def terminate_worker(self, ls_index: int, timeout: float = 0):
        wctl = self.workers[ls_index]
        wctl.is_alive = False
        wctl.is_sync = False
        for f in wctl.futures.values():
            f.cancel()

        wctl.reader.cancel()
        wctl.worker.exit_event.set()
        wctl.worker.output_queue.cancel_join_thread()
        wctl.worker.input_queue.cancel_join_thread()
        wctl.worker.output_queue.close()
        wctl.worker.input_queue.close()
        wctl.worker.join(timeout=timeout)
        logger.info(
            "TonlibManager: worker #{ls_index:03d} terminated, restart_count: {restart_count}",
            ls_index=ls_index,
            restart_count=wctl.restart_count,
        )

    def spawn_worker(self, ls_index: int, force_restart: bool = False):
        wctl: WorkerControl = None
        sync_verify_address = (
            self.collection_config.collections[0].address if self.collection_config.collections else None
        )
        if ls_index in self.workers:
            wctl = self.workers[ls_index]
            if not force_restart and wctl.worker.is_alive():
                logger.warning("TonlibManager: Worker #{ls_index:03d} already exists", ls_index=ls_index)
                return
            try:
                self.terminate_worker(ls_index, timeout=3)
            except Exception as E:
                logger.error(
                    "TonlibManager: Failed to delete existing worker #{ls_index:03d} process: {exc}",
                    ls_index=ls_index,
                    exc=E,
                )

            wctl.restart_count += 1
            wctl.set_worker(
                TonlibWorker(ls_index, self.settings, sync_verify_address=sync_verify_address),
                self.loop.create_task(self.read_results(ls_index)),
            )
        else:
            wctl = WorkerControl(
                TonlibWorker(ls_index, self.settings, sync_verify_address=sync_verify_address),
                self.loop.create_task(self.read_results(ls_index)),
            )
            self.workers[ls_index] = wctl

        logger.info(
            "TonlibManager: starting worker #{ls_index:03d}, restart_count: {restart_count}",
            ls_index=ls_index,
            restart_count=wctl.restart_count,
        )
        ctime = time.time()
        mtime = time.monotonic()
        wctl.start_mt = mtime
        wctl.start_time = ctime
        wctl.off_sync_mt = mtime
        wctl.off_sync_time = ctime
        wctl.off_sync_dur_ema = 0
        wctl.sync_time = 0
        wctl.sync_mt = 0
        wctl.sync_dur_ema = 0
        wctl.worker.start()
        wctl.is_alive = wctl.worker.is_alive()
        wctl.is_sync = False
        wctl.last_block = -1
        wctl.last_block_time = 0

    async def worker_control(self, ls_index, enabled):
        if enabled == False:
            self.terminate_worker(ls_index, timeout=3)
        self.workers[ls_index].is_enabled = enabled

    def log_liteserver_task(self, task_result: TonlibClientResult):
        result_type = None
        if isinstance(task_result.result, Mapping):
            result_type = task_result.result.get("@type", "unknown")
        else:
            result_type = type(task_result.result).__name__

        rec = {
            "timestamp": datetime.utcnow(),
            "elapsed": task_result.elapsed_time,
            "task_id": task_result.task_id,
            "method": task_result.method,
            "liteserver_info": task_result.liteserver_info,
            "result_type": result_type,
            "exception": task_result.exception,
        }

        logger.info(
            "TonlibManager: Received result of type: {result_type}, method: {method}, task_id: {task_id}", **rec
        )

    async def read_results(self, ls_index):
        wctl = self.workers[ls_index]
        while True:
            try:
                try:
                    msg_type, msg_content = await self.loop.run_in_executor(
                        self.threadpool_executor, wctl.worker.output_queue.get, True, 1
                    )
                except queue.Empty:
                    continue
                if msg_type == TonlibWorkerMsgType.TASK_RESULT and isinstance(msg_content, TonlibClientResult):
                    task_id = msg_content.task_id

                    if task_id in wctl.futures and not wctl.futures[task_id].done():
                        if msg_content.exception is not None:
                            wctl.futures[task_id].set_exception(msg_content.exception)
                        if msg_content.result is not None:
                            wctl.futures[task_id].set_result(msg_content.result)
                    else:
                        logger.warning(
                            "TonlibManager: received result from worker #{ls_index:03d} for unexpected task '{task_id}'",
                            ls_index=ls_index,
                            task_id=task_id,
                        )
                    self.log_liteserver_task(msg_content)

                if msg_type == TonlibWorkerMsgType.LAST_BLOCK_UPDATE:
                    if wctl.last_block != msg_content:
                        wctl.last_block = msg_content
                        wctl.last_block_time = time.time()

                if msg_type == TonlibWorkerMsgType.ARCHIVAL_UPDATE:
                    wctl.is_archival = msg_content
            except asyncio.CancelledError:
                logger.info(
                    'TonlibManager: Task "read_results" for worker #{ls_index:03d} was cancelled', ls_index=ls_index
                )
                return
            except:
                logger.error(
                    'TonlibManager: Task "read_results" for worker #{ls_index:03d} terminated with exception: {exc}',
                    ls_index=ls_index,
                    exc=traceback.format_exc(),
                )

    async def check_working(self):
        while True:
            try:
                last_blocks = [wctl.last_block for wctl in self.workers.values() if wctl.last_block != -1]
                if not last_blocks:
                    await asyncio.sleep(1)
                    continue

                best_block = max(last_blocks)
                consensus_block_seqno = 0
                # detect 'consensus':
                # it is no more than 3 blocks less than best block
                # at least 60% of ls know it
                # it is not earlier than prev
                strats = [sum([1 if ls == (best_block - i) else 0 for ls in last_blocks]) for i in range(4)]
                total_suitable = sum(strats)
                sm = 0
                for i, am in enumerate(strats):
                    sm += am
                    if sm >= total_suitable * 0.6:
                        consensus_block_seqno = best_block - i
                        break
                mtime = time.monotonic()
                ctime = int(time.time())
                if consensus_block_seqno > self.consensus_block:
                    self.consensus_block = consensus_block_seqno
                    self.consensus_block_mt = mtime
                for wctl in self.workers.values():
                    is_sync = wctl.last_block >= self.consensus_block
                    if is_sync != wctl.is_sync:
                        if is_sync:
                            if wctl.off_sync_mt:
                                duration = mtime - wctl.off_sync_mt
                                wctl.off_sync_dur_ema = wctl.off_sync_dur_ema * (1 - self.ema_alpha) + self.ema_alpha * duration
                                wctl.off_sync_duration += duration
                            wctl.sync_time = ctime
                            wctl.sync_mt = mtime
                        else:
                            wctl.off_sync_count += 1
                            if wctl.sync_mt:
                                duration = mtime - wctl.sync_mt
                                wctl.sync_dur_ema = wctl.sync_dur_ema * (1 - self.ema_alpha) + self.ema_alpha * duration
                                wctl.sync_duration += duration
                            wctl.off_sync_time = ctime
                            wctl.off_sync_mt = mtime
                        wctl.is_sync = is_sync
                        logger.info(
                            "TonlibManager: worker #{ls_index:03d} changed state, is_sync: {is_sync}, last_block: {last_block}, consensus: {consensus}",
                            ls_index=wctl.ls_index,
                            is_sync=is_sync,
                            last_block=wctl.last_block,
                            consensus=self.consensus_block,
                        )

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("TonlibManager[check_working]: Task was cancelled")
                return
            except:
                logger.critical(
                    "TonlibManager[check_working]: Task terminated with exception: {format_exc}",
                    format_exc=traceback.format_exc(),
                )
                await asyncio.sleep(10)

    async def check_children_alive(self):
        logger.warning("TonlibManager[check_children_alive]: entering main loop")
        while True:
            try:
                for ls_index in self.workers:
                    current_time = time.monotonic()
                    wctl = self.workers[ls_index]

                    _is_alive = wctl.worker.is_alive()
                    if wctl.is_alive and not _is_alive:
                        logger.error(
                            "TonlibManager[check_children_alive]: Worker #{ls_index:03d} is dead, exitcode: {exitcode}",
                            ls_index=ls_index,
                            exitcode=wctl.worker.exitcode,
                        )
                    wctl.is_alive = _is_alive
                    if (
                        not wctl.is_alive
                        and wctl.is_enabled
                        and current_time >= wctl.start_mt + self.restart_timeout
                    ):
                        self.spawn_worker(ls_index, force_restart=True)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("TonlibManager[check_children_alive]: Task was cancelled")
                return
            except:
                logger.critical(
                    "TonlibManager[check_children_alive]: Task terminated with exception: {exc}",
                    exc=traceback.format_exc(),
                )
                await asyncio.sleep(10)

    def get_workers_state(self):
        result = {}
        for ls_index, wctl in self.workers.items():
            result[ls_index] = asdict(wctl)
        return result

    def get_tonlib_state(self):
        return {
            "workers": self.get_workers_state(),
            "stats": self.stats.as_list(),
        }

    def select_worker(self, ls_index=None, archival=None, count=1):
        if count == 1 and ls_index is not None and self.workers[ls_index].is_sync:
            return ls_index

        suitable = [ls_index for ls_index, wctl in self.workers.items() if wctl.is_alive and wctl.is_sync and
                    (archival is None or wctl.is_archival == archival)]
        random.shuffle(suitable)
        if len(suitable) < count:
            logger.warning('TonlibManager: Required number of workers is not reached: found {found} of {count}', found=len(suitable), count=count)
        if len(suitable) == 0:
            raise RuntimeError(f'TonlibManager: No working liteservers with ls_index={ls_index}, archival={archival}')
        return suitable[:count] if count > 1 else suitable[0]

    async def dispatch_request_to_worker(self, method: str, ls_index: int, *args, **kwargs):
        task_id = "{}:{}".format(time.time(), random.random())
        timeout = time.monotonic() + self.settings.request_timeout
        with self.stats[StatisticTags(ls_index, method)]:
            wctl = self.workers[ls_index]
            wctl.tasks_count += 1
            wctl.pending_tasks += 1

            logger.info(
                "TonlibManager: ls_index: {ls_index:03d}, sending request method: {method}, task_id: {task_id}",
                method=method,
                task_id=task_id,
                ls_index=ls_index,
            )
            await self.loop.run_in_executor(
                self.threadpool_executor,
                wctl.worker.input_queue.put,
                (task_id, timeout, method, args, kwargs),
            )

            try:
                wctl.futures[task_id] = self.loop.create_future()
                await asyncio.wait_for(wctl.futures[task_id], timeout=self.settings.request_timeout + 1)
                result = wctl.futures[task_id].result()
                logger.info(
                    "TonlibManager: Worker #{ls_index:03d}, received result method: {method}, task_id: {task_id}",
                    method=method,
                    task_id=task_id,
                    ls_index=ls_index,
                )
                return result
            finally:
                wctl.pending_tasks -= 1
                wctl.futures.pop(task_id)

    async def dispatch_request(self, method: str, *args, **kwargs):
        stat_method = method
        if stat_method == "raw_run_method":
            stat_method += "_" + args[1]
        ls_index = self.select_worker()
        return await self.dispatch_request_to_worker(method, ls_index, *args, **kwargs)

    def dispatch_archival_request(self, method, *args, **kwargs):
        ls_index = None
        try:
            ls_index = self.select_worker(archival=True)
        except RuntimeError as E:
            logger.info(
                f"TonlibManager: Method {method} failed to execute on archival node: {E} -> fallback to normal node"
            )
            ls_index = self.select_worker(archival=False)
        return self.dispatch_request_to_worker(method, ls_index, *args, **kwargs)

    def get_measurements(self, timestamp: int) -> list[str]:
        excludes = {"ls_index", "last_block_time", "start_mt"}
        return self.stats.as_influx(timestamp) + \
                [f'NFTorrentLiteserverWorker,ls_index={x.ls_index} {dataclass_to_influx(x, excludes=excludes)} {timestamp}' for x in self.workers.values()]

    async def raw_run_method(self, address, method, stack_data, seqno):
        try:
            return await self.dispatch_request("raw_run_method", address, method, stack_data, seqno)
        except TonlibError:
            return await self.dispatch_archival_request("raw_run_method", address, method, stack_data, seqno)

    async def raw_get_account_state(self, address: str, seqno: int = None):
        method = "raw_get_account_state"
        try:
            addr = await self.dispatch_request(method, address, seqno)
        except TonlibError:
            addr = await self.dispatch_archival_request(method, address, seqno)
        return addr

    async def generic_get_account_state(self, address: str, seqno: int = None):
        method = "generic_get_account_state"
        try:
            addr = await self.dispatch_request(method, address, seqno)
        except TonlibError:
            addr = await self.dispatch_archival_request(method, address, seqno)
        return addr

    async def get_nft_item_address(self, collection_address, item_index):
        method = "get_nft_item_address"
        try:
            addr = await self.dispatch_request(method, collection_address, item_index)
        except TonlibError:
            addr = await self.dispatch_archival_request(method, collection_address, item_index)
        return addr

    async def get_nft_data(self, address: str, skip_verification: bool = False, owner: str = None) -> NftItemData:
        addr = TonAddress(address)
        nft_data_result = await self.raw_run_method(address, "get_nft_data", [], None)
        if nft_data_result["stack"] is None or len(nft_data_result["stack"]) != 5:
            raise TonlibRequestError("Smart contract is not NFT")

        nft_data = parse_nft_item_data(nft_data_result["stack"])
        if owner is not None and TonAddress(nft_data["owner_address"]) != TonAddress(owner):
            raise TonlibRequestError("NFT owner mistmach")

        nft_collection = None
        if nft_data["collection_address"] is not None:
            nft_collection = self.collection_config.get_collection(nft_data["collection_address"])
        if nft_collection is None:
            raise TonlibRequestError("NFT collection not known")

        if not skip_verification:
            verified_nft_address = await self.get_nft_item_address(nft_data["collection_address"], nft_data["index"])
            if TonAddress(verified_nft_address) != addr:
                raise TonlibRequestError("Verification with NFT collection failed")

        nft_data["individual_content"] = self.collection_config.nft_content_class.from_tvm(
            CellSlice(nft_data["individual_content"])
        )
        nft_data["address"] = addr.b64url
        return NftItemData(**nft_data)

    async def get_collection_data(self, address: str) -> CollectionData:
        nft_collection = self.collection_config.get_collection(address)
        if nft_collection is None:
            raise TonlibRequestError("NFT collection not known")

        collection_data_result = await self.raw_run_method(address, "get_collection_data", [], None)
        if collection_data_result["stack"] is None or len(collection_data_result["stack"]) != 3:
            raise TonlibRequestError("Smart contract is not NFT Collection")
        collection_data = parse_nft_collection_data(collection_data_result["stack"])

        collection_info_result = await self.raw_run_method(address, "get_info", [], None)
        info_class = self.collection_config.collection_info_class
        collection_data["collection_info"] = info_class.from_tvm(collection_info_result["stack"])
        collection_data["address"] = TonAddress(address).b64url
        return CollectionData(**collection_data)
