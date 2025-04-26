import asyncio
import base64
import hashlib
import heapq
import os
import queue
import random
import shutil
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from loguru import logger
from pyTON.cache import CacheManager, DisabledCacheManager

from NFTorrent import exceptions
from NFTorrent.address import parse_bag_id
from NFTorrent.settings import TonStorageCliSettings
from NFTorrent.storage import TonStorageLru
from NFTorrent.worker import (TonStorageCliWorker, WorkerCliTask,
                              WorkerCliTaskResult, WorkerStatusNotify)


@dataclass
class StorageCliStatus:
    is_alive: bool
    peer_count: int
    date_time: float
    recv_time: float


@dataclass
class WorkerControl:
    worker: TonStorageCliWorker
    reader: asyncio.Task
    is_alive: bool = False
    is_healthy: bool = False
    is_enabled: bool = True
    _start_time: float = 0
    start_time: float = 0
    restart_count: int = 0
    tasks_count: int = 0
    pending_tasks: int = 0
    cli_status: StorageCliStatus = None
    futures: Dict[str, any] = field(default_factory=dict)


class TonStorageCliManager:
    node_state_cache_timeout = 30

    def __init__(self,
                 settings: TonStorageCliSettings,
                 num_workers: int = None,
                 restart_timeout: int = None,
                 dispatcher: Optional[Any] = None,
                 cache_manager: Optional[CacheManager] = None,
                 loop: Optional[asyncio.BaseEventLoop] = None,
                 response_handler: Callable = None,
                 query_delete_lru: Callable = None,
                 ):
        self.num_workers = num_workers or settings.num_workers
        self.restart_timeout = restart_timeout or settings.restart_timeout
        self.settings = settings
        self.dispatcher = dispatcher
        self.cache_manager = cache_manager or DisabledCacheManager()
        self.node_state_time = 0
        self.node_state = None
        self.response_handler = response_handler
        self.query_delete_lru = query_delete_lru

        self.workers: Dict[int, WorkerControl] = {}
        self.storage_lru = TonStorageLru()
        self.tasks = {}
        self.stats: Dict[str, int] = Counter()

        # cache setup
        self.setup_cache()

        logger.warning("TonStorageCliManager: starting... workers: {num_workers}", num_workers=self.num_workers)
        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, self.num_workers * 4))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        for client_id in range(self.num_workers):
            self.spawn_worker(client_id)

        # running tasks
        self.tasks = {
            'check_children_alive': self.loop.create_task(self.check_children_alive()),
            'torrent_lru_manager': self.loop.create_task(self.torrent_lru_manager()),
        }

    async def shutdown(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.wait(self.tasks.values())
        await asyncio.wait([self.loop.create_task(self.worker_control(i, enabled=False)) for i in self.workers])

        self.threadpool_executor.shutdown()

    def setup_cache(self):
        self.node_list = self.cache_manager.cached(expire=15)(self.node_list)
        self.node_get = self.cache_manager.cached(expire=600)(self.node_get)

    def terminate_worker(self, client_id: int, timeout: float = 0):
        wctl = self.workers[client_id]
        wctl.is_alive = False
        wctl.is_healthy = False
        for f in wctl.futures.values():
            f.cancel()

        wctl.reader.cancel()
        wctl.worker.exit_event.set()
        wctl.worker.output_queue.cancel_join_thread()
        wctl.worker.input_queue.cancel_join_thread()
        wctl.worker.output_queue.close()
        wctl.worker.input_queue.close()
        wctl.worker.join(timeout=timeout)

    def spawn_worker(self, client_id: int, force_restart: bool = False):
        wctl: WorkerControl = None
        if client_id in self.workers:
            wctl = self.workers[client_id]
            if not force_restart and wctl.worker.is_alive():
                logger.warning("TonStorageCliManager: Worker #{client_id:03d} already exists",
                               client_id=client_id)
                return
            try:
                self.terminate_worker(client_id, timeout=3)
            except Exception as E:
                logger.error("TonStorageCliManager: Failed to delete existing worker #{client_id:03d} process: {exc}",
                             client_id=client_id, exc=E)

            wctl.restart_count += 1
            wctl.worker = TonStorageCliWorker(client_id, deepcopy(self.settings))
            wctl.reader = self.loop.create_task(self.read_results(client_id))
        else:
            wctl = WorkerControl(
                TonStorageCliWorker(client_id, deepcopy(self.settings)),
                self.loop.create_task(self.read_results(client_id)),
            )
            self.workers[client_id] = wctl

        logger.info("TonStorageCliManager: starting worker #{client_id:03d}, restart_count: {restart_count}",
                    client_id=client_id, restart_count=wctl.restart_count)
        wctl._start_time = time.monotonic()
        wctl.start_time = time.time()
        wctl.worker.start()
        wctl.is_alive = wctl.worker.is_alive()

    async def worker_control(self, client_id, enabled):
        if not enabled:
            self.terminate_worker(client_id, timeout=3)
        self.workers[client_id].is_enabled = enabled

    async def read_results(self, client_id):
        wctl = self.workers[client_id]
        while True:
            try:
                try:
                    msg = await self.loop.run_in_executor(self.threadpool_executor,
                                                          wctl.worker.output_queue.get, True, 1)
                except queue.Empty:
                    continue
                if isinstance(msg, WorkerCliTaskResult):
                    task_id = msg.task_id

                    if task_id in wctl.futures and not wctl.futures[task_id].done():
                        if msg.exception is not None:
                            wctl.futures[task_id].set_exception(msg.exception)
                        if msg.result is not None:
                            wctl.futures[task_id].set_result(msg.result)
                    else:
                        logger.warning("TonStorageCliManager: received result from worker #{client_id:03d} for unexpected task '{task_id}'",  # noqa: E501
                                       client_id=client_id, task_id=task_id)

                if isinstance(msg, WorkerStatusNotify):
                    wctl.cli_status = StorageCliStatus(msg.is_alive, msg.peer_count, msg.date_time, time.monotonic())

            except asyncio.CancelledError:
                logger.info("TonStorageCliManager: Task \"read_results\" for worker #{client_id:03d} was cancelled",
                            client_id=client_id)
                return
            except (Exception, BaseException):
                logger.error("TonStorageCliManager: Task \"read_results\" for worker #{client_id:03d} terminated with exception: {exc}",  # noqa: E501
                             client_id=client_id, exc=traceback.format_exc())

    async def _torrent_lru_manager_process_bag(self, bag_id: str):
        processed = False
        while not processed:
            try:
                torrent_info = await self.node_get(bag_id)
                # 1. Delete all incomplete torrents
                delete_reason = None
                if not torrent_info['torrent']['completed']:
                    delete_reason = 'incomplete'

                # 2. Delete all torrents with size limit exceeded
                if not torrent_info['torrent']['total_size'] or \
                        int(torrent_info['torrent']['total_size']) > self.settings.storage_bag_size_limit:
                    delete_reason = 'size limit=' + torrent_info['torrent']['total_size']

                # 3. Delete all torrents which have at least min_redundancy+1 completed copies
                copies_count = peers = None
                if not delete_reason:
                    peers = await self.node_get_peers(bag_id)
                    copies_count = len([
                        x for x in peers['peers']
                        if x['ready_parts'] == peers['total_parts']
                    ])
                    if copies_count > self.settings.min_redundancy:
                        delete_reason = f'redundancy={copies_count}'
                # 4. Query delete LRU
                if not delete_reason and self.query_delete_lru is not None:
                    delete_reason = await self.query_delete_lru(bag_id, peers, torrent_info)

                if delete_reason:
                    logger.warning("TonStorageCliManager[torrent_lru_manager]: remove, BAG_ID: {bag_id}, reason: {reason}",  # noqa: E501
                                   bag_id=bag_id, reason=delete_reason)
                    self.stats['lru_recyle'] += 1
                    try:
                        await self.node_remove(bag_id)
                    except (Exception, BaseException):
                        self.stats['lru_recyle_error'] += 1
                        raise
                else:
                    self.storage_lru.upsert(bag_id)
                processed = True
            except asyncio.CancelledError:
                raise
            except exceptions.TorrentNotFound:
                logger.warning("TonStorageCliManager[torrent_lru_manager]: torrent not found, BAG_ID: {bag_id}",  # noqa: E501
                               bag_id=bag_id)
                shutil.rmtree(os.path.join(self.settings.storage_db_torrent_path, bag_id))
            except (exceptions.TorrentClientError, OSError, asyncio.exceptions.TimeoutError) as E:
                logger.warning("TonStorageCliManager[torrent_lru_manager]: error, BAG_ID: {bag_id}, {exc}",  # noqa: E501
                               bag_id=bag_id, exc=str(E))
                await asyncio.sleep(10)

    async def torrent_lru_manager(self):
        while True:
            try:
                self.storage_lru = TonStorageLru()

                logger.warning("TonStorageCliManager[torrent_lru_manager]: reading path: {path}",
                               path=self.settings.storage_db_torrent_path)
                path = Path(self.settings.storage_db_torrent_path)
                mtime_queue = []
                bulk_cnt = 0
                for file in path.iterdir():
                    bulk_cnt += 1
                    if not file.is_dir():
                        continue
                    try:
                        bag_id = parse_bag_id(file.name)
                    except ValueError:
                        continue

                    if bag_id == self.settings.manifest_bag_id:
                        continue

                    heapq.heappush(mtime_queue, (file.stat().st_mtime, bag_id))
                    if bulk_cnt == 100:
                        bulk_cnt = 0
                        await asyncio.sleep(0.1)

                logger.warning("TonStorageCliManager[torrent_lru_manager]: found torrents: {count}",
                               count=len(mtime_queue))

                bulk_cnt = 0
                while len(mtime_queue):
                    bulk_cnt += 1
                    _, bag_id = heapq.heappop(mtime_queue)
                    self.storage_lru.upsert_back(bag_id)
                    if bulk_cnt == 100:
                        bulk_cnt = 0
                        await asyncio.sleep(0.1)

                logger.warning("TonStorageCliManager[torrent_lru_manager]: entering main loop")
                while True:
                    await asyncio.sleep(3)

                    first_bag_id = None
                    while self.storage_lru.size > self.settings.storage_size_pressure:
                        bag_id, _ = self.storage_lru.remove_back()
                        if first_bag_id is None:
                            first_bag_id = bag_id
                        elif first_bag_id == bag_id:
                            logger.error("TonStorageCliManager[torrent_lru_manager]: can't keep limits, size: {size}, pressure: {pressure}",  # noqa: E501
                                         size=self.storage_lru.size,
                                         pressure=self.settings.storage_size_pressure)
                            await asyncio.sleep(30)
                            break
                        self._torrent_lru_manager_process_bag(bag_id)

            except asyncio.CancelledError:
                logger.info("TonStorageCliManager[torrent_lru_manager]: Task was cancelled")
                return
            except (Exception, BaseException):
                logger.error("TonStorageCliManager[torrent_lru_manager]: Task terminated with exception: {exc}",
                             exc=traceback.format_exc())
                await asyncio.sleep(300)

    async def check_children_alive(self):
        logger.warning("TonStorageCliManager[check_children_alive]: entering main loop")
        while True:
            try:
                try:
                    await self.get_node_state()
                except Exception as E:
                    logger.info("TonStorageCliManager[check_children_alive]: failed to get node state, exc: {exc}",
                                exc=str(E))

                for client_id in self.workers:
                    current_time = time.monotonic()
                    wctl = self.workers[client_id]

                    _is_alive = wctl.worker.is_alive()
                    if wctl.is_alive and not _is_alive:
                        logger.error("TonStorageCliManager[check_children_alive]: Worker #{client_id:03d} is dead, exitcode: {exitcode}",  # noqa: E501
                                     client_id=client_id, exitcode=wctl.worker.exitcode)
                    wctl.is_alive = _is_alive

                    wctl.is_healthy = wctl.is_alive and \
                        wctl.cli_status is not None \
                        and wctl.cli_status.is_alive and \
                        wctl.cli_status.peer_count > 0 and \
                        wctl.cli_status.recv_time >= current_time - wctl.worker.report_state_interval * 2

                    if not wctl.is_alive and wctl.is_enabled and \
                            current_time >= wctl._start_time + self.restart_timeout:
                        self.spawn_worker(client_id, force_restart=True)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("TonStorageCliManager[check_children_alive]: Task was cancelled")
                return
            except (Exception, BaseException):
                logger.critical("TonStorageCliManager[check_children_alive]: Task terminated with exception: {exc}",
                                exc=traceback.format_exc())
                await asyncio.sleep(10)

    def get_cached_node_state(self):
        return self.node_state

    async def get_node_state(self):
        curr_time = time.monotonic()
        if self.node_state is None or curr_time > self.node_state_time + self.node_state_cache_timeout:
            try:
                state = await self.node_get_state()
            except exceptions.TorrentNotFound:
                await self.dispatch_request('cmd_add', self.settings.manifest_bag_id)
                await asyncio.sleep(1)
                state = await self.node_get_state()

            self.node_state_time = curr_time
            self.node_state = state
        return self.node_state

    def get_storage_state(self):
        return {
            'workers': self.get_workers_state(),
            'size': self.storage_lru.size,
            'max_size': self.settings.storage_max_size,
            'size_pressure': self.settings.storage_size_pressure,
            'stats': self.stats,
        }

    def get_workers_state(self):
        result = {}
        for client_id, wctl in self.workers.items():
            result[client_id] = {
                'client_id': client_id,
                'is_healthy': wctl.is_healthy,
                'is_enabled': wctl.is_enabled,
                'start_time': wctl.start_time,
                'restart_count': wctl.restart_count,
                'tasks_count': wctl.tasks_count,
                'pending_tasks': wctl.pending_tasks
            }
        return result

    def select_worker(self, count=1):
        suitable = [
            (client_id, wctl.pending_tasks) for client_id, wctl in self.workers.items()
            if wctl.is_alive and wctl.is_healthy
        ]
        if len(suitable) == 0:
            # fallback
            suitable = [
                (client_id, wctl.pending_tasks) for client_id, wctl in self.workers.items()
                if wctl.is_alive
            ]

        if len(suitable) == 0:
            raise exceptions.TorrentClientError("No working clients")

        min_load = min(map(lambda x: x[1], suitable))
        suitable = [client_id for (client_id, load) in suitable if load == min_load]

        random.shuffle(suitable)
        if len(suitable) < count:
            logger.warning("TonStorageCliManager: Required number of workers is not reached: found {working_count} of {count}",  # noqa: E501
                           working_count=len(suitable), count=count)

        return suitable[:count] if count > 1 else suitable[0]

    async def dispatch_request_to_worker(self, method: str, client_id: int, *args, **kwargs):
        task_id = "{}:{}".format(time.time(), random.random())
        timeout = time.monotonic() + self.settings.request_timeout
        wctl = self.workers[client_id]
        wctl.tasks_count += 1
        wctl.pending_tasks += 1

        logger.info("TonStorageCliManager: Worker #{client_id:03d}, sending request method: {method}, task_id: {task_id}",  # noqa: E501
                    method=method, task_id=task_id, client_id=client_id)
        await self.loop.run_in_executor(self.threadpool_executor, wctl.worker.input_queue.put,
                                        WorkerCliTask(task_id, timeout, method, args, kwargs))

        try:
            wctl.futures[task_id] = self.loop.create_future()
            await asyncio.wait_for(wctl.futures[task_id], timeout=self.settings.request_timeout + 1)
            result = wctl.futures[task_id].result()
            logger.info("TonStorageCliManager: Worker #{client_id:03d}, received result method: {method}, task_id: {task_id}",  # noqa: E501
                        method=method, task_id=task_id, client_id=client_id)
        finally:
            wctl.pending_tasks -= 1
            wctl.futures.pop(task_id)

        return result

    async def dispatch_request(self, method: str, *args, **kwargs):
        try:
            self.stats[method] += 1
            client_id = self.select_worker()
            response = await self.dispatch_request_to_worker(method, client_id, *args, **kwargs)
            if self.response_handler:
                _response = self.response_handler(response)
                if _response is not None:
                    response = _response
            return response
        except Exception:
            self.stats[f'{method}_error'] += 1
            raise

    def _torrent_info_make_files_digest(self, torrent_info: Dict[str, Any], bag_id: str):
        if 'files' not in torrent_info:
            return

        for f in torrent_info['files']:
            digest = hashlib.shake_256((bag_id + f['name']).encode()).digest(15)
            f['digest'] = base64.b32encode(digest).decode().lower()

    async def node_get_state(self):
        method = 'node_get_state'
        return await self.dispatch_request(method)

    async def node_list(self):
        method = 'cmd_list'
        return await self.dispatch_request(method)

    async def node_create(self, path: str, description: str | dict | list = None,
                          copy: bool = False, no_upload: bool = False,
                          check_existance: bool = True):
        method = 'cmd_create'
        result = await self.dispatch_request(method, path, description=description,
                                             copy=copy, no_upload=no_upload,
                                             check_existance=check_existance)
        bag_id = parse_bag_id(result['torrent']['hash'])
        self.storage_lru.upsert(bag_id)
        self._torrent_info_make_files_digest(result, bag_id)
        return result

    async def node_add(self, bag_id: str | bytes, paused: bool = False):
        bag_id = parse_bag_id(bag_id)
        method = 'cmd_add'
        result = await self.dispatch_request(method, bag_id, paused=paused)
        self.storage_lru.upsert(bag_id)
        return result

    async def node_remove(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'cmd_remove'
        result = await self.dispatch_request(method, bag_id)
        self.storage_lru.remove(bag_id)
        return result

    async def node_upload_resume(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'cmd_upload_resume'
        return await self.dispatch_request(method, bag_id)

    async def node_download_resume(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'cmd_download_resume'
        return await self.dispatch_request(method, bag_id)

    async def node_upload_suspend(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'cmd_upload_suspend'
        return await self.dispatch_request(method, bag_id)

    async def node_get(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'cmd_get'
        result = await self.dispatch_request(method, bag_id)
        self._torrent_info_make_files_digest(result, bag_id)
        return result

    async def node_get_peers(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'cmd_get_peers'
        return await self.dispatch_request(method, bag_id)


async def __example():  # pragma: no cover
    import json

    manager = TonStorageCliManager(
        TonStorageCliSettings(
            storage_cli_binary="/mnt/c/Work/ton-storage/storage-daemon-cli.exe",
            storage_daemon_addr="172.19.96.1:5555",
            storage_db_path="C:/Work/ton-storage/storage-db",
            request_timeout=1,
            manifest_bag_id='A8C27C0AF2BB3A3077330F1857C3130F6EBEEE5BD5347A18F1A4CCD30D4F5F82'
        ),
        num_workers=4
    )

    await asyncio.sleep(1)
    logger.debug("Dump workers state: {state}", state=(json.dumps(manager.get_workers_state())))

    await asyncio.wait([
        manager.node_list(),
        manager.node_add('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
        manager.node_get('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
        manager.node_get_peers('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
        manager.node_remove('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
    ], return_when=asyncio.ALL_COMPLETED)

    logger.debug("Dump workers state: {state}", state=(json.dumps(manager.get_workers_state())))

    await manager.shutdown()
