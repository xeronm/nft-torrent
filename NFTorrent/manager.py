import asyncio
import time
import traceback
import random
import queue

from collections.abc import Mapping
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

from pyTON.cache import CacheManager, DisabledCacheManager

from .storage import TonStorageCliSettings, parse_bag_id
from .worker import TonStorageCliWorker

from pytonlib import TonlibError

from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

import logging

logger = logging.getLogger(__name__)

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

        self.workers = {}
        self.futures = {}
        self.tasks = {}

        # cache setup
        self.setup_cache()

        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, num_workers * 4))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        for client_id in range(num_workers):
            self.spawn_worker(client_id)

        # running tasks
        self.tasks['check_working'] = self.loop.create_task(self.check_working())
        self.tasks['check_children_alive'] = self.loop.create_task(self.check_children_alive())

    async def shutdown(self):
        for i in self.futures:
            self.futures[i].cancel()
        
        self.tasks['check_working'].cancel()
        await self.tasks['check_working']
        
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

    def spawn_worker(self, client_id: int, force_restart: bool = False):
        if client_id in self.workers:
            worker_info = self.workers[client_id]
            if not force_restart and worker_info.is_alive():
                logger.warning('Worker for liteserver #{ls_index} already exists', ls_index=ls_index)
                return
            try:
                worker_info['reader'].cancel()  
                worker_info['worker'].exit_event.set()
                worker_info['worker'].output_queue.cancel_join_thread()
                worker_info['worker'].input_queue.cancel_join_thread()
                worker_info['worker'].output_queue.close()
                worker_info['worker'].input_queue.close()
                worker_info['worker'].join(timeout=3)
            except Exception as ee:
                logger.error('Failed to delete existing process: {exc}', exc=ee)
        # running new worker
        if not client_id in self.workers:
            self.workers[client_id] = {
                'is_working': False,
                'is_enabled': True,
                'restart_count': -1,
                'tasks_count': 0
            }
        
        settings = deepcopy(self.settings)
        self.workers[client_id]['worker'] = TonStorageCliWorker(client_id, settings)
        self.workers[client_id]['reader'] = self.loop.create_task(self.read_results(client_id))
        self.workers[client_id]['worker'].start()
        self.workers[client_id]['restart_count'] += 1

    async def worker_control(self, ls_index, enabled):
        if enabled == False:
            self.workers[ls_index]['reader'].cancel()
            self.workers[ls_index]['worker'].exit_event.set()

            self.workers[ls_index]['worker'].output_queue.cancel_join_thread()
            self.workers[ls_index]['worker'].input_queue.cancel_join_thread()
            self.workers[ls_index]['worker'].output_queue.close()
            self.workers[ls_index]['worker'].input_queue.close()

            self.workers[ls_index]['worker'].join()
            
            await self.workers[ls_index]['reader']

        self.workers[ls_index]['is_enabled'] = enabled

    def log_liteserver_task(self, task_result: TonlibClientResult):
        result_type = None
        if isinstance(task_result.result, Mapping):
            result_type = task_result.result.get('@type', 'unknown')
        else:
            result_type = type(task_result.result).__name__
        details = {}
        
        rec = {
            'timestamp': datetime.utcnow(),
            'elapsed': task_result.elapsed_time,
            'task_id': task_result.task_id,
            'method': task_result.method,
            'liteserver_info': task_result.liteserver_info,
            'result_type': result_type,
            'exception': task_result.exception 
        }

        logger.info("Received result of type: {result_type}, method: {method}, task_id: {task_id}", **rec)

    async def read_results(self, ls_index):
        worker = self.workers[ls_index]['worker']
        while True:
            try:
                try:
                    msg_type, msg_content = await self.loop.run_in_executor(self.threadpool_executor, worker.output_queue.get, True, 1)
                except queue.Empty:
                    continue
                if msg_type == TonlibWorkerMsgType.TASK_RESULT:
                    task_id = msg_content.task_id

                    if task_id in self.futures and not self.futures[task_id].done():
                        if msg_content.exception is not None:
                            self.futures[task_id].set_exception(msg_content.exception)
                        if msg_content.result is not None:    
                            self.futures[task_id].set_result(msg_content.result)
                    else:
                        logger.warning("TonlibManager received result from TonlibWorker #{ls_index:03d} whose task '{task_id}' doesn't exist or is done.", ls_index=ls_index, task_id=task_id)

                    self.log_liteserver_task(msg_content)

                if msg_type == TonlibWorkerMsgType.LAST_BLOCK_UPDATE:
                    worker.last_block = msg_content

                if msg_type == TonlibWorkerMsgType.ARCHIVAL_UPDATE:
                    worker.is_archival = msg_content
            except asyncio.CancelledError:
                logger.info("Task read_results from TonlibWorker #{ls_index:03d} was cancelled", ls_index=ls_index)
                return
            except:
                logger.error("read_results exception {format_exc}", format_exc=traceback.format_exc())
        
    async def check_working(self):
        while True:
            try:
                last_blocks = [self.workers[ls_index]['worker'].last_block for ls_index in self.workers]
                best_block = max([i for i in last_blocks])
                consensus_block_seqno = 0
                # detect 'consensus':
                # it is no more than 3 blocks less than best block
                # at least 60% of ls know it
                # it is not earlier than prev
                last_blocks_non_zero = [i for i in last_blocks if i != 0]
                strats = [sum([1 if ls == (best_block-i) else 0 for ls in last_blocks_non_zero]) for i in range(4)]
                total_suitable = sum(strats)
                sm = 0
                for i, am in enumerate(strats):
                    sm += am
                    if sm >= total_suitable * 0.6:
                        consensus_block_seqno = best_block - i
                        break
                if consensus_block_seqno > self.consensus_block.seqno:
                    self.consensus_block.seqno = consensus_block_seqno
                    self.consensus_block.timestamp = datetime.utcnow().timestamp()
                for ls_index in self.workers:
                    self.workers[ls_index]['is_working'] = last_blocks[ls_index] >= self.consensus_block.seqno

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info('Task check_working was cancelled')
                return
            except:
                logger.critical('Task check_working dead: {format_exc}', format_exc=traceback.format_exc())

    async def check_children_alive(self):
        while True:
            try:
                for client_id in self.workers:
                    worker_info = self.workers[client_id]
                    worker_info['is_enabled'] = worker_info['is_enabled'] or time.time() > worker_info.get('time_to_alive', 1e10)
                    if worker_info['restart_count'] >= 3:
                        worker_info['is_enabled'] = False
                        worker_info['time_to_alive'] = time.time() + 10 * 60
                        worker_info['restart_count'] = 0
                    if not worker_info['worker'].is_alive() and worker_info['is_enabled']:
                        logger.error(f'TonStorageCliManager: worker #{client_id:03d} is dead, exit={worker_info.exit_code}.')
                        self.spawn_worker(client_id, force_restart=True)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info('TonStorageCliManager: Task check_children_alive was cancelled')
                return
            except:
                logger.critical(f'TonStorageCliManager: Task check_children_alive dead: {traceback.format_exc()}')

    def get_workers_state(self):
        result = {}
        for client_id, worker_info in self.workers.items():
            result[client_id] = {
                'client_id': client_id,
                'is_working': worker_info['is_working'],
                'is_enabled': worker_info['is_enabled'],
                'restart_count': worker_info['restart_count'],
                'tasks_count': worker_info['tasks_count']
            }
        return result

    def select_worker(self, client_id=None, archival=None, count=1):
        if count == 1 and client_id is not None and self.workers[client_id]['is_working']:
            return client_id 

        suitable = [
            client_id for client_id, worker_info in self.workers.items() 
            if worker_info['is_working']
        ]
        random.shuffle(suitable)
        if len(suitable) < count:
            logger.warning(f'TonStorageCliManager: Required number of workers is not reached: found {len(suitable)} of {count}')
        if len(suitable) == 0:
            raise RuntimeError(f'No working liteservers with ls_index={client_id}, archival={archival}')
        return suitable[:count] if count > 1 else suitable[0]

    async def dispatch_request_to_worker(self, method: str, client_id: int, *args, **kwargs):
        task_id = "{}:{}".format(time.time(), random.random())
        timeout = time.monotonic() + self.settings.request_timeout
        self.workers[client_id]['tasks_count'] += 1

        logger.info('TonStorageCliManager: Sending request method: %s, task_id: %s, client_id: %03d', 
            method, task_id, client_id)
        await self.loop.run_in_executor(self.threadpool_executor, self.workers[client_id]['worker'].input_queue.put, (task_id, timeout, method, args, kwargs))

        try:
            self.futures[task_id] = self.loop.create_future()
            await self.futures[task_id]
            return self.futures[task_id].result()
        finally:
            self.futures.pop(task_id)

    def dispatch_request(self, method: str, *args, **kwargs):
        ls_index = self.select_worker()
        return self.dispatch_request_to_worker(method, ls_index, *args, **kwargs)

    async def node_get_state(self):
        method = 'node_get_state'
        return await self.dispatch_request(method)

    async def node_list(self):
        bag_id = parse_bag_id(bag_id)
        method = 'run_list'
        return await self.dispatch_request(method, bag_id)

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
    
