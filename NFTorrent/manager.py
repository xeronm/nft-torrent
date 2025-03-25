import asyncio
import time
import traceback
import random
import queue

from collections.abc import Mapping
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

from pyTON.cache import CacheManager, DisabledCacheManager

from NFTorrent.storage import TonStorageCliSettings, parse_bag_id
from NFTorrent.worker import TonStorageCliWorker, WorkerCliTask, WorkerCliTaskResult, WorkerStatusNotify

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

import logging

logger = logging.getLogger(__name__)


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
    start_time: float = 0
    restart_count: int = 0
    tasks_count: int = 0
    pending_tasks: int = 0
    cli_status: StorageCliStatus = None
    futures: Dict[str, any] = field(default_factory=dict)

class TonStorageCliManager:

    def __init__(self,
                 settings: TonStorageCliSettings,
                 num_workers: int = 4,
                 dispatcher: Optional["Dispatcher"]=None,
                 cache_manager: Optional["CacheManager"]=None,
                 loop: Optional[asyncio.BaseEventLoop]=None):
        self.num_workers = num_workers
        self.settings = settings
        self.dispatcher = dispatcher
        self.cache_manager = cache_manager or DisabledCacheManager()

        self.workers: Dict[int, WorkerControl] = {}
        self.tasks = {}

        # cache setup
        self.setup_cache()

        logger.info('TonStorageCliManager: starting... workers: %d', num_workers)
        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, num_workers * 3))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        for client_id in range(num_workers):
            self.spawn_worker(client_id)

        # running tasks
        self.tasks['check_children_alive'] = self.loop.create_task(self.check_children_alive())

    async def shutdown(self):        
        self.tasks['check_children_alive'].cancel()
        await self.tasks['check_children_alive']

        await asyncio.wait([self.loop.create_task(self.worker_control(i, enabled=False)) for i in self.workers])

        self.threadpool_executor.shutdown()

    def setup_cache(self):        
        pass
        # self.raw_get_transactions = self.cache_manager.cached(expire=5)(self.raw_get_transactions)
        # self.get_transactions = self.cache_manager.cached(expire=15, check_error=False)(self.get_transactions)
        # self.raw_get_account_state = self.cache_manager.cached(expire=5)(self.raw_get_account_state)
        # self.generic_get_account_state = self.cache_manager.cached(expire=5)(self.generic_get_account_state)
        # self.raw_run_method = self.cache_manager.cached(expire=5)(self.raw_run_method)
        # self.raw_estimate_fees = self.cache_manager.cached(expire=5)(self.raw_estimate_fees)
        # self.getMasterchainInfo = self.cache_manager.cached(expire=1)(self.getMasterchainInfo)
        # self.getMasterchainBlockSignatures = self.cache_manager.cached(expire=5)(self.getMasterchainBlockSignatures)
        # self.getShardBlockProof = self.cache_manager.cached(expire=5)(self.getShardBlockProof)
        # self.lookupBlock = self.cache_manager.cached(expire=600)(self.lookupBlock)
        # self.getShards = self.cache_manager.cached(expire=600)(self.getShards)
        # self.raw_getBlockTransactions = self.cache_manager.cached(expire=600)(self.raw_getBlockTransactions)
        # self.getBlockTransactions = self.cache_manager.cached(expire=600)(self.getBlockTransactions)
        # self.getBlockHeader = self.cache_manager.cached(expire=600)(self.getBlockHeader)
        # self.get_config_param = self.cache_manager.cached(expire=5)(self.get_config_param)
        # self.get_token_data = self.cache_manager.cached(expire=15)(self.get_token_data)
        # self.tryLocateTxByOutcomingMessage = self.cache_manager.cached(expire=600, check_error=False)(self.tryLocateTxByOutcomingMessage)
        # self.tryLocateTxByIncomingMessage = self.cache_manager.cached(expire=600, check_error=False)(self.tryLocateTxByIncomingMessage)


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
                logger.warning('TonStorageCliManager: worker #%03d already exists', client_id)
                return
            try:
                self.terminate_worker(client_id, timeout=3)
            except Exception as E:
                logger.error('TonStorageCliManager: Failed to delete existing process: {%s}', E)

            wctl.restart_count += 1
            wctl.worker = TonStorageCliWorker(client_id, deepcopy(self.settings))
            wctl.reader = self.loop.create_task(self.read_results(client_id))
        else:
            wctl = WorkerControl(
                TonStorageCliWorker(client_id, deepcopy(self.settings)),
                self.loop.create_task(self.read_results(client_id)),
            )
            self.workers[client_id] = wctl

        logger.info('TonStorageCliManager: starting worker #%03d, restart_count: %d', client_id, wctl.restart_count)        
        wctl.start_time = time.monotonic()
        wctl.worker.start()

    async def worker_control(self, client_id, enabled):
        if enabled == False:            
           self.terminate_worker(client_id, timeout=3)
        self.workers[client_id].is_enabled = enabled

    async def read_results(self, client_id):
        wctl = self.workers[client_id]
        while True:
            try:
                try:
                    msg = await self.loop.run_in_executor(self.threadpool_executor, wctl.worker.output_queue.get, True, 1)
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
                        logger.warning(f'TonStorageCliManager: received result from worker #{client_id:03d} whose task "{task_id}" doesn\'t exist or is done')

                if isinstance(msg, WorkerStatusNotify):
                    wctl.cli_status = StorageCliStatus(msg.is_alive, msg.peer_count, msg.date_time, time.monotonic())

            except asyncio.CancelledError:
                logger.info("TonStorageCliManager: Task read_results from worker #%03d was cancelled", client_id)
                return
            except:
                logger.error("TonStorageCliManager: read_results exception {%s}", traceback.format_exc())

    async def check_children_alive(self):
        while True:
            try:
                for client_id in self.workers:
                    current_time = time.monotonic()
                    wctl = self.workers[client_id]
                    
                    _is_alive = wctl.worker.is_alive()
                    if wctl.is_alive and not _is_alive:
                        logger.error('TonStorageCliManager: worker #%03d is dead, exit=%d.', client_id, wctl.worker.exitcode)
                    wctl.is_alive = _is_alive

                    wctl.is_healthy = wctl.is_alive and wctl.cli_status is not None and wctl.cli_status.is_alive and \
                        wctl.cli_status.peer_count > 0 and wctl.cli_status.recv_time >= current_time - wctl.worker.report_state_interval * 2
                    
                    if not wctl.is_alive and wctl.is_enabled and current_time >= wctl.start_time + 30:
                        self.spawn_worker(client_id, force_restart=True)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info('TonStorageCliManager: Task check_children_alive was cancelled')
                return
            except:
                logger.critical(f'TonStorageCliManager: Task check_children_alive dead: {traceback.format_exc()}')

    def get_workers_state(self):
        result = {}
        current_time = time.time() - time.monotonic()
        for client_id, wctl in self.workers.items():
            result[client_id] = {
                'client_id': client_id,
                'is_healthy': wctl.is_healthy,
                'is_enabled': wctl.is_enabled,
                'start_time': current_time + wctl.start_time,
                'restart_count': wctl.restart_count,
                'tasks_count': wctl.tasks_count,
                'pending_tasks': wctl.pending_tasks
            }
        return result

    def select_worker(self, client_id=None, archival=None, count=1):
        if count == 1 and client_id is not None:
            return client_id 

        suitable = [
            (client_id, wctl.pending_tasks) for client_id, wctl in self.workers.items()
            if wctl.is_alive and wctl.is_healthy
        ]
        if not suitable:
            # fallback
            suitable = [
                (client_id, wctl.pending_tasks) for client_id, wctl in self.workers.items() 
                if wctl.is_alive
            ]

        min_load = min(map(lambda x: x[1], suitable))
        suitable = [client_id for (client_id, load) in suitable if load == min_load]

        random.shuffle(suitable)
        if len(suitable) < count:
            logger.warning(f'TonStorageCliManager: Required number of workers is not reached: found {len(suitable)} of {count}')
        if len(suitable) == 0:
            raise RuntimeError(f'No working liteservers with ls_index={client_id}, archival={archival}')
        return suitable[:count] if count > 1 else suitable[0]

    async def dispatch_request_to_worker(self, method: str, client_id: int, *args, **kwargs):
        task_id = "{}:{}".format(time.time(), random.random())
        timeout = time.monotonic() + self.settings.request_timeout
        wctl = self.workers[client_id]
        wctl.tasks_count += 1
        wctl.pending_tasks += 1

        logger.info('TonStorageCliManager: Sending request method: %s, task_id: %s, client_id: %03d', 
            method, task_id, client_id)
        await self.loop.run_in_executor(self.threadpool_executor, wctl.worker.input_queue.put, WorkerCliTask(task_id, timeout, method, args, kwargs))

        try:
            wctl.futures[task_id] = self.loop.create_future()
            await asyncio.wait_for(wctl.futures[task_id], timeout=self.settings.request_timeout + 1)
            result = wctl.futures[task_id].result()
            logger.info('TonStorageCliManager: Received result: %s, task_id: %s, client_id: %03d', 
                method, task_id, client_id)
        finally:
            wctl.pending_tasks -= 1
            wctl.futures.pop(task_id)

        return result


    def dispatch_request(self, method: str, *args, **kwargs):
        ls_index = self.select_worker()
        return self.dispatch_request_to_worker(method, ls_index, *args, **kwargs)

    async def node_get_state(self):
        method = 'node_get_state'
        return await self.dispatch_request(method)

    async def node_list(self):
        method = 'run_list'
        return await self.dispatch_request(method)

    async def node_create(self, path: str, description: str | dict | list = None, copy: bool = False, check_existance: bool = True):
        method = 'run_create'
        return await self.dispatch_request(method, path, description=description, copy=copy, check_existance=check_existance)

    async def node_add(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'run_add'
        return await self.dispatch_request(method, bag_id)

    async def node_remove(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'run_remove'
        return await self.dispatch_request(method, bag_id)

    async def node_get(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'run_get'
        return await self.dispatch_request(method, bag_id)

    async def node_get_peers(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        method = 'run_get_peers'
        return await self.dispatch_request(method, bag_id)
    

async def __example():  # pragma: no cover
    import json
    logging.basicConfig(level=logging.INFO)

    manager = TonStorageCliManager(
        TonStorageCliSettings(
            storage_cli_binary="/mnt/c/Work/ton-storage/storage-daemon-cli.exe",
            storage_cli_args=["-I", "172.19.96.1:5555"],
            storage_db_path="C:/Work/ton-storage/storage-db",
            request_timeout=1,
            manifest_bag_id='A8C27C0AF2BB3A3077330F1857C3130F6EBEEE5BD5347A18F1A4CCD30D4F5F82'
        ),
        num_workers=4
    )

    await asyncio.sleep(1)
    print(json.dumps(manager.get_workers_state()))


    await asyncio.wait([
        manager.node_list(), 
        manager.node_add('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
        manager.node_get('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
        manager.node_get_peers('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
        manager.node_remove('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871'),
    ], return_when=asyncio.ALL_COMPLETED)

    print(json.dumps(manager.get_workers_state()))

    await manager.shutdown()