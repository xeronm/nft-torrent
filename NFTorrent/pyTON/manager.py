import asyncio
import random
import time
from collections import Counter
from typing import Dict

from loguru import logger
from pyTON.manager import TonlibManager as _TonlibManager
from pytonlib import TonlibError
from pytonlib.utils.address import detect_address
from pytonlib.utils.tokens import (parse_nft_collection_data,
                                   parse_nft_item_data)
from tonpy.types import CellSlice

from NFTorrent.modelsbase import CollectionConfig, CollectionData, NftItemData


class ContractRequestError(Exception):
    pass


class TonlibManager(_TonlibManager):

    def __init__(self, *args, collection_config: CollectionConfig = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.collection_config = collection_config
        self.stats: Dict[str, int] = Counter()

    def get_tonlib_state(self):
        return {
            'workers': self.get_workers_state(),
            'stats': self.stats,
        }

    async def dispatch_request_to_worker(self, method, ls_index, *args, **kwargs):
        task_id = "{}:{}".format(time.time(), random.random())
        timeout = time.time() + self.tonlib_settings.request_timeout
        self.workers[ls_index]['tasks_count'] += 1

        logger.info("Sending request method: {method}, task_id: {task_id}, ls_index: {ls_index}",
                    method=method, task_id=task_id, ls_index=ls_index)
        await self.loop.run_in_executor(self.threadpool_executor, self.workers[ls_index]['worker'].input_queue.put,
                                        (task_id, timeout, method, args, kwargs))

        try:
            self.futures[task_id] = self.loop.create_future()
            await asyncio.wait_for(self.futures[task_id], timeout=self.tonlib_settings.request_timeout + 1)
            return self.futures[task_id].result()
        finally:
            self.futures.pop(task_id)

    async def dispatch_request(self, method: str, *args, **kwargs):
        stat_method = method
        if stat_method == 'raw_run_method':
            stat_method += '_' + args[1]
        try:
            self.stats[stat_method] += 1
            ls_index = self.select_worker()
            return await self.dispatch_request_to_worker(method, ls_index, *args, **kwargs)
        except Exception:
            self.stats[f'{stat_method}_error'] += 1
            raise

    async def get_nft_item_address(self, collection_address, item_index):
        method = 'get_nft_item_address'
        try:
            addr = await self.dispatch_request(method, collection_address, item_index)
        except TonlibError:
            addr = await self.dispatch_archival_request(method, collection_address, item_index)
        return addr

    async def get_nft_data(self, address: str, skip_verification: bool = False, owner: str = None) -> NftItemData:
        nft_data_result = await self.raw_run_method(address, 'get_nft_data', [], None)
        if nft_data_result['stack'] is None or len(nft_data_result['stack']) != 5:
            raise ContractRequestError("Smart contract is not NFT")

        nft_data = parse_nft_item_data(nft_data_result['stack'])
        if owner is not None and detect_address(nft_data['owner'])['raw_form'] != detect_address(owner)['raw_form']:
            raise ContractRequestError("NFT owner mistmach")

        nft_collection = None
        if nft_data['collection_address'] is not None:
            nft_collection = self.collection_config.get_collection(nft_data['collection_address'])
        if nft_collection is None:
            raise ContractRequestError("NFT collection not known")

        if not skip_verification:
            verified_nft_address = await self.get_nft_item_address(nft_data['collection_address'], nft_data['index'])
            if detect_address(verified_nft_address)['raw_form'] != detect_address(address)['raw_form']:
                raise ContractRequestError("Verification with NFT collection failed")

        # print(nft_data['individual_content'])
        nft_data['individual_content'] = self.collection_config.nft_content_class.from_tvm(
            CellSlice(nft_data['individual_content']))
        nft_data['address'] = detect_address(address)['bounceable']['b64url']

        return NftItemData(**nft_data)

    async def get_collection_data(self, address: str) -> CollectionData:
        nft_collection = self.collection_config.get_collection(address)
        if nft_collection is None:
            raise ContractRequestError("NFT collection not known")

        collection_data_result = await self.raw_run_method(address, 'get_collection_data', [], None)
        if collection_data_result['stack'] is None or len(collection_data_result['stack']) != 3:
            raise ContractRequestError("Smart contract is not NFT Collection")
        collection_data = parse_nft_collection_data(collection_data_result['stack'])

        collection_info_result = await self.raw_run_method(address, 'info', [], None)
        info_class = self.collection_config.collection_info_class
        collection_data['collection_info'] = info_class.from_tvm(collection_info_result['stack'])
        collection_data['address'] = detect_address(address)['bounceable']['b64url']
        return CollectionData(**collection_data)

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
