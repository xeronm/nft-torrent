import asyncio
import datetime
import io
import logging
import math
import pickle
import random
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import (
    dataclass,
)

import aiohttp
from fastapi import status
from PIL import Image
from pytonlib import TonlibException
from sqlalchemy.exc import NoResultFound
from sqlmodel import Field, Session, SQLModel, create_engine, select

from NFTorrent.cache import BaseCacheManager, DisabledCacheManager
from NFTorrent.ipfs import IpfsRpcManager
from NFTorrent.models import CollectionData
from NFTorrent.modelsbase import (
    BaseNftModel,
    CollectionConfig,
    CollectionInstance,
    MeasurementStore,
    StatisticMeasurement,
    StatisticNoTags,
)
from NFTorrent.settings import IndexDbSettings
from NFTorrent.tonlib import TonlibManager, TonlibRequestError

logger = logging.getLogger(__name__)


class BaseCollectionModel(SQLModel, table=False):
    id: int = Field(default=None, primary_key=True)
    address: str = Field(unique=True, max_length=48)
    index: int = Field()
    image: str | None = Field(default=None, max_length=256)
    image_data: bytes | None = Field(default=None)
    icons: bytes | None = Field(default=None)


@dataclass
class CollectionTaskData:
    nft_collection: CollectionInstance
    collection_data: CollectionData = None
    instance: BaseCollectionModel = None


@dataclass(frozen=True)
class StatisticTags:
    address: str


@dataclass
class CollectionMeasurement:
    db_next_index: int = 0
    bc_next_index: int = 0
    nft_index_count: int = 0
    nft_index_error: int = 0
    last_checked: int = 0
    last_updated: int = 0


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
        cache_manager: BaseCacheManager | None = None,
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
        self.stats = MeasurementStore("NFTorrentIndexer", CollectionMeasurement)
        self.collection_config = collection_config
        self.cache_manager = cache_manager or DisabledCacheManager()

        self.indexer_tasks = {}

        # cache setup
        self.setup_cache()

        logger.warning("Initializing database...")
        self.dbengine = create_engine(self.settings.database_url)
        SQLModel.metadata.create_all(self.dbengine)

        logger.warning("Starting... workers: %d", self.num_workers)
        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, self.num_workers))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        self.collections: dict[str, CollectionTaskData] = {}

        # running tasks
        for c in self.collection_config.collections:
            data = CollectionTaskData(c, instance=self.sync_collection_upsert(c))
            self.collections[c.b64url] = data
            self.indexer_tasks[c.b64url] = self.loop.create_task(self.nft_indexer(data))

    async def shutdown(self):
        for task in self.indexer_tasks.values():
            task.cancel()
        await asyncio.wait(self.indexer_tasks.values())
        self.threadpool_executor.shutdown()

    def setup_cache(self):
        self.collection_query = self.cache_manager.cached(expire=60)(self.collection_query)
        self.collection_random_feed = self.cache_manager.cached(expire=600)(self.collection_random_feed)

    async def nft_indexer(self, data: CollectionTaskData):
        address = data.nft_collection.b64url
        meas: CollectionMeasurement = self.stats[StatisticTags(address)]
        logger.warning("[%s]: Indexer task entering main loop", address)
        while True:
            await asyncio.sleep(self.settings.indexer_timeout)
            try:
                if self.tonlib is None:
                    continue
                if sum([1 for x in self.tonlib.get_workers_state().values() if x["is_sync"]]) == 0:
                    logger.warning("[%s]: No active Tonlib workers", address)
                    continue

                logger.info("[%s]: Updating collection info...", address)
                # Refresh data from DB
                data.instance = await self.loop.run_in_executor(
                    self.threadpool_executor, self.sync_collection_upsert, data.nft_collection
                )
                meas.db_next_index = data.instance.index

                # Refresh data from TON
                data.collection_data = await self.tonlib.get_collection_data(address)
                next_index = data.collection_data.next_item_index
                meas.bc_next_index = next_index
                if data.instance.index > next_index:
                    logger.error(
                        "[%s]: Collection On-Chain index less than IndexDB, db_index: %d, chain_index: %d",  # noqa: E501
                        address,
                        data.instance.index,
                        next_index,
                    )
                elif data.instance.index < next_index:
                    logger.info(
                        "[%s]: Collection IndexDB, db_index: %d, chain_index: %d",  # noqa: E501
                        address,
                        data.instance.index,
                        next_index,
                    )
                    bulk = []
                    while data.instance.index < next_index and len(bulk) < self.settings.bulk_size:
                        nft_address = await self.tonlib.get_nft_item_address(address, data.instance.index)
                        logger.info(
                            "[%s]: Indexing NFT, address: %s",
                            address,
                            nft_address,
                        )
                        try:
                            nft_data = await self.tonlib.get_nft_data(nft_address, skip_verification=True)
                            if nft_data.index != data.instance.index:
                                raise TonlibRequestError("NFT index mistmath")
                            model_class = self.collection_config.dbmodel_nft_class

                            bulk.append(model_class.from_nftmodel(collection_id=data.instance.id, data=nft_data))
                        except TonlibRequestError as E:
                            meas.nft_index_error += 1
                            logger.warning(
                                "[%s]: Contract request error, address: %s, index: %d - %s: %s",  # noqa: E501
                                address,
                                nft_address,
                                data.instance.index,
                                type(E).__name__,
                                E,
                            )
                        data.instance.index += 1

                    if len(bulk):
                        await self.collection_nft_make_icons(bulk)
                        await self.loop.run_in_executor(
                            self.threadpool_executor, self.sync_collection_nft_bulk_insert, data.instance, bulk
                        )
                        meas.nft_index_count += len(bulk)
                        meas.last_updated = int(time.time())
                        meas.db_next_index = data.instance.index

                meas.last_checked = int(time.time())
            except (TonlibException, asyncio.TimeoutError) as E:
                logger.warning(
                    "[%s]: Got error - %s: %s",
                    address,
                    type(E).__name__,
                    E,
                )
            except asyncio.CancelledError:
                logger.info("[%s]: Indexer task was cancelled", address)
                return
            except (Exception, BaseException):
                logger.exception(
                    "[%s]: Indexer task got unhandled exception, sleep for %d", address, self.restart_timeout
                )
                await asyncio.sleep(self.restart_timeout)

    async def collection_nft_make_icon(self, instance: BaseNftModel):
        buffer = None
        if instance.image:
            logger.info(
                "Getting image for NFT icons, address: %s, uri: %s",
                instance.address,
                instance.image,
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
                                    "NFT icons, got http image error, address: %s, status: %s, text: %s",  # noqa: E501
                                    instance.address,
                                    resp.status,
                                    await resp.text(),
                                )
                            else:
                                buffer = await resp.read()
            except Exception as E:
                instance.error_time = datetime.datetime.now(datetime.timezone.utc)
                instance.error_code = type(E).__name__[:40]
                logger.warning(
                    "NFT icons, get http image error, address: %s - %s: %s",
                    instance.address,
                    type(E).__name__,
                    E,
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
                "NFT icons convert error, address: %s - %s: %s", instance.address, type(E).__name__, E
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
                instance = session.exec(select(model_class).where(model_class.address == collection.b64url)).one()
            except NoResultFound:
                instance = None
            if instance is None:
                instance = model_class(address=collection.b64url, index=0)
                session.add(instance)
                session.commit()
                session.refresh(instance)
        return instance

    def get_indexdb_state(self):
        return {
            "collections": [
                {"config": x.nft_collection, "blockchain": x.collection_data} for x in self.collections.values()
            ],
            "stats": self.stats.as_list(),
        }

    def get_measurements(self, timestamp: int) -> list[str]:
        return self.stats.as_influx(timestamp)

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

            select_stmt = select(model_class).where(model_class.error_time == None)  # noqa: E711
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
