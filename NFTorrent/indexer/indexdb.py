import asyncio
import datetime
import io
import math
import pickle
import random
import time
import traceback
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import aiohttp
from fastapi import status
from loguru import logger
from PIL import Image
from pyTON.cache import CacheManager, DisabledCacheManager
from pytonlib import TonlibException
from sqlalchemy.exc import NoResultFound
from sqlmodel import Field, Session, SQLModel, create_engine, select

from NFTorrent.ipfs import IpfsRpcManager
from NFTorrent.models import CollectionData
from NFTorrent.modelsbase import BaseNftModel, CollectionConfig, CollectionInstance
from NFTorrent.pyTON.manager import ContractRequestError, TonlibManager
from NFTorrent.settings import IndexDbSettings
from NFTorrent.utils import dict_to_influx


class BaseCollectionModel(SQLModel, table=False):
    id: int = Field(default=None, primary_key=True)
    address: str = Field(unique=True, max_length=48)
    index: int = Field()
    image: str | None = Field(default=None, max_length=256)
    image_data: bytes | None = Field(default=None)
    bag_id: str | None = Field(default=None)
    icons: bytes | None = Field(default=None)


@dataclass
class CollectionTaskData:
    nft_collection: CollectionInstance
    collection_data: CollectionData = None
    instance: BaseCollectionModel = None
    stats: dict[str, int] = field(default_factory=Counter)


def _convert_image(buffer: bytes, size: int, format: str) -> bytes:
    img = Image.open(io.BytesIO(buffer))
    # 1. Resize min dimension to `size`
    x, y = img.size
    if x > size and y > size:
        m, n = x / size, y / size
        x0 = y0 = size
        if m > n:
            x0 = math.ceil(x / n)
        elif n > m:
            y0 = math.ceil(y / m)
        img = img.resize([x0, y0])

    # 2. Crop center
    x, y = img.size
    if x > size or y > size:
        x0 = y0 = 0
        if x > size:
            x0 = (x - size) // 2
        if y > size:
            y0 = (y - size) // 2
        img = img.crop((x0, y0, x0 + size, y0 + size))

    bufferOut = io.BytesIO()
    img.save(bufferOut, format)
    return bufferOut.getvalue()


class IndexDb:

    def __init__(
        self,
        settings: IndexDbSettings,
        num_workers: int = None,
        restart_timeout: int = None,
        cache_manager: CacheManager | None = None,
        loop: asyncio.BaseEventLoop | None = None,
        collection_config: CollectionConfig = None,
        tonlib: TonlibManager = None,
        ipfs: IpfsRpcManager = None,
    ):

        self.num_workers = num_workers or settings.num_workers
        self.restart_timeout = restart_timeout or 60
        self.settings = settings
        self.tonlib = tonlib
        self.ipfs = ipfs
        self.collection_config = collection_config
        self.cache_manager = cache_manager or DisabledCacheManager()

        self.indexer_tasks = {}

        # cache setup
        self.setup_cache()

        logger.warning("IndexDb: Initializing database...")
        self.dbengine = create_engine(self.settings.database_url)
        SQLModel.metadata.create_all(self.dbengine)

        logger.warning("IndexDb: starting... workers: {num_workers}", num_workers=self.num_workers)
        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, self.num_workers))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        self.collections: dict[str, CollectionTaskData] = {}

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
                if sum([1 for x in self.tonlib.get_workers_state().values() if x["is_working"]]) == 0:
                    logger.warning("IndexDb[nft_indexer:{address}]: No active Tonlib workers")
                    continue

                # Refresh data from DB
                data.instance = await self.loop.run_in_executor(
                    self.threadpool_executor, self.sync_collection_upsert, data.nft_collection
                )
                # Refresh data from TON
                data.collection_data = await self.tonlib.get_collection_data(address)
                next_index = data.collection_data.next_item_index
                if data.instance.index > next_index:
                    logger.error(
                        "IndexDb[nft_indexer:{address}]: collection On-Chain index less than IndexDB, db_index: {index}, chain_index: {new_index}",  # noqa: E501
                        address=address,
                        index=data.instance.index,
                        new_index=next_index,
                    )
                elif data.instance.index < next_index:
                    logger.info(
                        "IndexDb[nft_indexer:{address}]: collection IndexDB, db_index: {index}, chain_index: {new_index}",  # noqa: E501
                        address=address,
                        index=data.instance.index,
                        new_index=next_index,
                    )
                    bulk = []
                    while data.instance.index < next_index and len(bulk) < self.settings.bulk_size:
                        nft_address = await self.tonlib.get_nft_item_address(address, data.instance.index)
                        logger.info(
                            "IndexDb[nft_indexer:{address}]: indexing NFT, address: {nft_address}",
                            address=address,
                            nft_address=nft_address,
                        )
                        try:
                            nft_data = await self.tonlib.get_nft_data(nft_address, skip_verification=True)
                            if nft_data.index != data.instance.index:
                                raise ContractRequestError("NFT index mistmath")
                            model_class = self.collection_config.dbmodel_nft_class

                            bulk.append(model_class.from_nftmodel(collection_id=data.instance.id, data=nft_data))
                        except ContractRequestError as E:
                            data.stats["nft_index_error"] += 1
                            logger.warning(
                                "IndexDb[nft_indexer:{address}]: Contract request error, address: {nft_address}, index: {index}, {exc}",  # noqa: E501
                                address=address,
                                nft_address=nft_address,
                                index=data.instance.index,
                                exc=str(E),
                            )
                        data.instance.index += 1

                    if len(bulk):
                        await self.collection_nft_make_icons(bulk)
                        await self.loop.run_in_executor(
                            self.threadpool_executor, self.sync_collection_nft_bulk_insert, data.instance, bulk
                        )
                        data.stats["nft_index_count"] += len(bulk)
                        data.stats["last_updated"] = int(time.time())

                data.stats["last_checked"] = int(time.time())
            except (TonlibException, asyncio.TimeoutError) as E:
                logger.warning(
                    "IndexDb[nft_indexer:{address}]: Got error - {errclass}: {exc}",
                    address=address,
                    errclass=type(E),
                    exc=str(E),
                )
            except asyncio.CancelledError:
                logger.info("IndexDb[nft_indexer:{address}]: Task was cancelled", address=address)
                return
            except (Exception, BaseException):
                logger.critical(
                    "IndexDb[nft_indexer:{address}]: Task terminated with exception: {exc}",
                    address=address,
                    exc=traceback.format_exc(),
                )
                await asyncio.sleep(self.restart_timeout)

    async def collection_nft_make_icon(self, instance: BaseNftModel):
        buffer = None
        if instance.image:
            logger.info(
                "IndexDb: getting image for NFT icons, address: {address}, uri: {image_uri}",
                address=instance.address,
                image_uri=instance.image,
            )
            try:
                if instance.image.startswith("ipfs://"):
                    buffer, _ = await self.ipfs.get_cid_file(uri=instance.image)
                else:
                    timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with await session.get(instance.image) as resp:
                            if resp.status != status.HTTP_200_OK:
                                logger.warning(
                                    "IndexDb: NFT icons, get http image error, address: {address}, status: {status}, text: {text}",  # noqa: E501
                                    address=instance.address,
                                    status=resp.status,
                                    text=await resp.text(),
                                )
                            else:
                                buffer = await resp.read()
            except Exception as E:
                instance.error_time = datetime.datetime.now(datetime.timezone.utc)
                instance.error_code = type(E).__name__[:40]
                logger.warning(
                    "IndexDb: NFT icons, get http image error, address: {address}, {exc}",
                    address=instance.address,
                    exc=str(E),
                )
                return False

        if instance.image_data is not None:
            buffer = instance.image_data

        if buffer is None:
            return False
        try:
            small = await self.loop.run_in_executor(
                self.threadpool_executor,
                _convert_image,
                buffer,
                self.settings.icon_size_small,
                self.settings.icon_format,
            )
            medium = await self.loop.run_in_executor(
                self.threadpool_executor,
                _convert_image,
                buffer,
                self.settings.icon_size_medium,
                self.settings.icon_format,
            )
            instance.icons = pickle.dumps({"small": [small], "medium": [medium]})
        except Exception as E:
            instance.error_time = datetime.datetime.now(datetime.timezone.utc)
            instance.error_code = type(E).__name__[:40]
            logger.warning(
                "IndexDb: NFT icons convert error, address: {address}, {exc}", address=instance.address, exc=str(E)
            )
            return False
        return True

    async def collection_nft_make_icons(self, instances: list[BaseNftModel]):
        sem = asyncio.Semaphore(self.settings.max_parallel_task)

        async def _sem_wrapper(instance: BaseNftModel):
            async with sem:
                await self.collection_nft_make_icon(instance)

        tasks = [_sem_wrapper(x) for x in instances]
        await asyncio.gather(*tasks)

    def sync_collection_nft_bulk_insert(self, instance: BaseCollectionModel, bulk: list[BaseCollectionModel]):
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
                instance = session.exec(
                    select(model_class).where(model_class.address == collection.address_url())
                ).one()
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
            k: {"address": v.instance.address, "next_index": v.instance.index, "stats": v.stats}
            for k, v in self.collections.items()
        }

    def get_measurements(self, timestamp: int) -> list[str]:
        return [
            f'NFTorrentIndexer,address={k} {dict_to_influx(dict(**item["stats"], next_index=item["next_index"]))} {timestamp}'  # noqa: E501
            for k, item in self.get_indexdb_state().items()
        ]

    def sync_collection_query(self, limit: int = 100, offset: int = None, **kwargs):
        model_class = self.collection_config.dbmodel_nft_class
        with Session(self.dbengine) as session:
            select_stmt = select(model_class).where(model_class.error_time is None)
            for col, value in kwargs.items():
                if value is not None:
                    select_stmt = select_stmt.where(getattr(model_class, col) == value)

            if offset is not None:
                select_stmt = select_stmt.offset(offset)
            if limit is not None:
                select_stmt = select_stmt.limit(limit)
            return session.exec(select_stmt).all()

    async def collection_query(self, icon_size: str = None, **kwargs):

        def _warped_func(kwargs):
            return self.sync_collection_query(**kwargs)

        _collections = {x.instance.id: x.instance.address for x in self.collections.values()}

        result = await self.loop.run_in_executor(self.threadpool_executor, _warped_func, kwargs)
        return [x.to_nftheader(_collections.get(x.collection_id), icon_size=icon_size) for x in result]

    def sync_collection_random_feed(self, limit: int = 100, **kwargs):
        model_class = self.collection_config.dbmodel_nft_class
        segment_size = 1 << math.ceil(math.log2(limit)) + 1
        result: Sequence[BaseNftModel] = []
        with Session(self.dbengine) as session:
            last_item = session.exec(select(model_class).order_by(model_class.id.desc())).first()
            last_id = last_item.id if last_item is not None else 0
            segment_count = last_id // segment_size
            n = round(random.random() * segment_count)
            x0 = p0 = segment_size * n
            x1 = p1 = p0 + segment_size

            select_stmt = select(model_class).where(model_class.error_time is None)
            for col, value in kwargs.items():
                if value is not None:
                    select_stmt = select_stmt.where(getattr(model_class, col) == value)

            # segment tree climbing
            while len(result) < segment_size:
                result += session.exec(
                    select_stmt.where(model_class.id >= x0).where(model_class.id < x1).limit(segment_size - len(result))
                ).all()
                if p0 <= 0 and p1 >= last_id:
                    break
                if n % 2 == 1:
                    x1 = p0
                    x0 = p0 = x1 - (p1 - x1)
                else:
                    x0 = p1
                    x1 = p1 = x0 + (x0 - p0)
                n = n / 2

        random.shuffle(result)
        return result[:limit]

    async def collection_random_feed(self, offset: int, icon_size: str = None, **kwargs):

        def _warped_func(kwargs):
            return self.sync_collection_random_feed(**kwargs)

        _collections = {x.instance.id: x.instance.address for x in self.collections.values()}

        result = await self.loop.run_in_executor(self.threadpool_executor, _warped_func, kwargs)
        return [x.to_nftheader(_collections.get(x.collection_id), icon_size=icon_size) for x in result]
