import asyncio
import math
import random
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from loguru import logger
from pyTON.cache import CacheManager, DisabledCacheManager
from sqlalchemy.exc import NoResultFound
from sqlmodel import Field, Session, SQLModel, create_engine, select

from NFTorrent.models import CollectionData
from NFTorrent.modelsbase import (BaseNftModel, CollectionConfig,
                                  CollectionInstance)
from NFTorrent.pyTON.manager import ContractRequestError, TonlibManager
from NFTorrent.settings import IndexDbSettings


class BaseCollectionModel(SQLModel, table=False):
    id: int = Field(default=None, primary_key=True)
    address: str = Field(unique=True, max_length=48)
    index: int = Field()


@dataclass
class CollectionTaskData:
    nft_collection: CollectionInstance
    collection_data: CollectionData = None
    instance: BaseCollectionModel = None
    stats: Dict[str, int] = field(default_factory=Counter)


class IndexDb:

    def __init__(self,
                 settings: IndexDbSettings,
                 num_workers: int = None,
                 restart_timeout: int = None,
                 cache_manager: Optional[CacheManager] = None,
                 loop: Optional[asyncio.BaseEventLoop] = None,
                 collection_config: CollectionConfig = None,
                 tonlib: TonlibManager = None
                 ):

        self.num_workers = num_workers or settings.num_workers
        self.restart_timeout = restart_timeout or 60
        self.settings = settings
        self.tonlib = tonlib
        self.collection_config = collection_config
        self.cache_manager = cache_manager or DisabledCacheManager()

        self.indexer_tasks = {}

        # cache setup
        self.setup_cache()

        logger.warning('IndexDb: Initializing database...')
        self.dbengine = create_engine(self.settings.database_url)
        SQLModel.metadata.create_all(self.dbengine)

        logger.warning("IndexDb: starting... workers: {num_workers}", num_workers=self.num_workers)
        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, self.num_workers))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        self.collections: Dict[str, CollectionTaskData] = {}

        # running tasks
        for c in self.collection_config.collections:
            data = CollectionTaskData(c, instance=self.sync_collection_upsert(c))
            self.collections[c.address] = data
            self.indexer_tasks[c.address] = self.loop.create_task(self.nft_indexer(data))

    async def shutdown(self):
        for task in self.indexer_tasks.values():
            task.cancel()
        await asyncio.wait(self.indexer_tasks.values())
        self.threadpool_executor.shutdown()

    def setup_cache(self):
        self.collection_query = self.cache_manager.cached(expire=60)(self.collection_query)
        self.collection_random_feed = self.cache_manager.cached(expire=600)(self.collection_random_feed)

    async def nft_indexer(self, data: CollectionTaskData):
        address = data.nft_collection.address
        logger.warning("IndexDb[nft_indexer:{address}]: Collection indexer, entering main loop", address=address)
        while True:
            await asyncio.sleep(self.settings.indexer_timeout)
            logger.info("IndexDb[nft_indexer:{address}]: Updating collection info...", address=address)
            try:
                if self.tonlib is None:
                    continue
                if sum([1 for x in self.tonlib.get_workers_state().values() if x['is_working']]) == 0:
                    logger.warning("IndexDb[nft_indexer:{address}]: No active Tonlib workers")
                    continue

                # Refresh data from DB
                data.instance = await self.loop.run_in_executor(self.threadpool_executor,
                                                                self.sync_collection_upsert, data.nft_collection)
                # Refresh data from TON
                data.collection_data = await self.tonlib.get_collection_data(address)

                next_index = data.collection_data.next_item_index
                if data.instance.index > next_index:
                    logger.error("IndexDb[nft_indexer:{address}]: collection On-Chain next_index={new_index} less than IndexDB next_index={index}",  # noqa: E501
                                 address=address, index=data.instance.index, new_index=next_index)
                elif data.instance.index < next_index:
                    logger.info('IndexDb[nft_indexer:{address}]: collection IndexDB next_index={index}, On-Chain next_index={new_index}',  # noqa: E501
                                address=address, index=data.instance.index, new_index=next_index)
                    bulk = []
                    while data.instance.index < next_index and len(bulk) < self.settings.bulk_size:
                        nft_address = await self.tonlib.get_nft_item_address(address, data.instance.index)
                        logger.info('IndexDb[nft_indexer:{address}]: indexing NFT with address={nft_address}',
                                    address=address, nft_address=nft_address)
                        try:
                            nft_data = await self.tonlib.get_nft_data(nft_address, skip_verification=True)
                            if nft_data.index != data.instance.index:
                                raise ContractRequestError("NFT index mistmath")
                            model_class = self.collection_config.dbmodel_nft_class
                            bulk.append(model_class.from_nftmodel(collection_id=data.instance.id,
                                                                  data=nft_data))
                        except ContractRequestError as E:
                            data.stats['nft_index_error'] += 1
                            logger.warning("IndexDb[nft_indexer:{address}]: Contract request error, address: {nft_address}, index={index}, {exc}",  # noqa: E501
                                           address=address,
                                           nft_address=nft_address,
                                           index=data.instance.index,
                                           exc=str(E))
                        data.instance.index += 1

                    if len(bulk):
                        await self.loop.run_in_executor(self.threadpool_executor,
                                                        self.sync_collection_nft_bulk_insert, data.instance, bulk)
                        data.stats['nft_index_count'] += len(bulk)

            except asyncio.TimeoutError:
                logger.warning("IndexDb[nft_indexer:{address}]: async operation timeout",
                               address=address)
            except asyncio.CancelledError:
                logger.info("IndexDb[nft_indexer:{address}]: Task was cancelled", address=address)
                return
            except (Exception, BaseException):
                logger.critical("IndexDb[nft_indexer:{address}]: Task terminated with exception: {exc}",
                                address=address, exc=traceback.format_exc())
                await asyncio.sleep(self.restart_timeout)

    def sync_collection_nft_bulk_insert(self, instance: BaseCollectionModel, bulk: List[SQLModel]):
        with Session(self.dbengine) as session:
            for nft_instance in bulk:
                session.add(nft_instance)
            session.add(instance)
            session.commit()
            session.refresh(instance)

    def sync_collection_upsert(self, collection: CollectionInstance) -> BaseCollectionModel:
        model_class = self.collection_config.dbmodel_class
        with Session(self.dbengine) as session:
            try:
                instance = session.exec(select(model_class)
                                        .where(model_class.address == collection.address_url())).one()
            except NoResultFound:
                instance = None
            if instance is None:
                instance = model_class(address=collection.address_url(), index=0)
                session.add(instance)
                session.commit()
                session.refresh(instance)
        return instance

    def get_indexdb_state(self):
        return {
            k: {
                'address': v.instance.address,
                'next_index': v.instance.index,
                'stats': v.stats
            }
            for k, v in self.collections.items()
        }

    def sync_collection_query(self, limit: int = 100, offset: int = None, **kwargs):
        model_class = self.collection_config.dbmodel_nft_class
        with Session(self.dbengine) as session:
            select_stmt = select(model_class)
            for col, value in kwargs.items():
                if value is not None:
                    select_stmt = select_stmt.where(getattr(model_class, col) == value)

            if offset is not None:
                select_stmt = select_stmt.offset(offset)
            if limit is not None:
                select_stmt = select_stmt.limit(limit)
            return session.exec(select_stmt).all()

    async def collection_query(self, **kwargs):

        def _warped_func(kwargs):
            return self.sync_collection_query(**kwargs)

        _collections = {x.instance.id: x.instance.address for x in self.collections.values()}

        result = await self.loop.run_in_executor(self.threadpool_executor, _warped_func, kwargs)
        return [x.to_nftheader(_collections.get(x.collection_id)) for x in result]

    def sync_collection_random_feed(self, limit: int = 100, **kwargs):
        model_class = self.collection_config.dbmodel_nft_class
        segment_size = 1 << math.ceil(math.log2(limit)) + 1
        result: Sequence[BaseNftModel] = []
        with Session(self.dbengine) as session:
            last_item = session.exec(select(model_class).order_by(model_class.id.desc())).first()
            last_id = last_item.id if last_item is not None else 0
            segment_count = last_id//segment_size
            n = round(random.random()*segment_count)
            x0 = p0 = segment_size * n
            x1 = p1 = p0 + segment_size

            select_stmt = select(model_class)
            for col, value in kwargs.items():
                if value is not None:
                    select_stmt = select_stmt.where(getattr(model_class, col) == value)

            # segment tree climbing
            while len(result) < segment_size:
                result += session.exec(select_stmt
                                       .where(model_class.id >= x0)
                                       .where(model_class.id < x1)
                                       .limit(segment_size - len(result))).all()
                if p0 <= 0 and p1 >= last_id:
                    break
                if n % 2 == 1:
                    x1 = p0
                    x0 = p0 = x1 - (p1 - x1)
                else:
                    x0 = p1
                    x1 = p1 = x0 + (x0 - p0)
                n = n/2

        random.shuffle(result)
        return result[:limit]

    async def collection_random_feed(self, offset: int, **kwargs):

        def _warped_func(kwargs):
            return self.sync_collection_random_feed(**kwargs)

        _collections = {x.instance.id: x.instance.address for x in self.collections.values()}

        result = await self.loop.run_in_executor(self.threadpool_executor, _warped_func, kwargs)
        return [x.to_nftheader(_collections.get(x.collection_id)) for x in result]
