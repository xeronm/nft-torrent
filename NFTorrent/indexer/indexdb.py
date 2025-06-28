import asyncio
import datetime
import io
import logging
import math
import pickle
import random
import time
import etcd3
import copy

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import (
    dataclass,
)

import aiohttp
from fastapi import status
from PIL import Image
from pytonlib import TonlibException
from sqlalchemy.exc import NoResultFound, SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, select

from NFTorrent.cache import BaseCacheManager, DisabledCacheManager
from NFTorrent.ipfs import IpfsRpcManager
from NFTorrent.models import CollectionData
from NFTorrent.modelsbase import (
    CollectionConfig,
    CollectionInstance,
    MeasurementStore,
)
from NFTorrent.dbmodels import NftTaskQueue, NftTaskType, TgUser, PetsCollection, PetMemoryNft
from NFTorrent.settings import IndexDbSettings
from NFTorrent.tonlib import TonlibManager, TonlibRequestError
from .notifications import BotChannel

logger = logging.getLogger(__name__)


@dataclass
class CollectionTaskData:
    nft_collection: CollectionInstance
    collection_data: CollectionData = None
    instance: PetsCollection = None


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


class EtcdLockError(Exception):
    pass

class EtcdPoolLock:

    def __init__(self, lock_name: str, etcd_clients: list[etcd3.Etcd3Client], threadpool_executor: ThreadPoolExecutor, lock_ttl: int = 15):
        self.lock_name = lock_name
        self.lock_ttl = lock_ttl
        self.etcd_clients = etcd_clients
        self.threadpool_executor = threadpool_executor
        self._lock: etcd3.Lock = None

    def __enter__(self):
        if not self.etcd_clients:
            return

        for etcd in self.etcd_clients:
            try:
                status = etcd.status()
                lock = etcd.lock(name=self.lock_name, ttl=self.lock_ttl)
                if lock.acquire():
                    self._lock = lock
                    return
            except etcd3.Etcd3Exception as E:
                pass
        raise EtcdLockError('Unable to acquire Lock')

    def __exit__(self):
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.threadpool_executor, self.__enter__)

    async def __aexit__(self, exc_type, exc, tb):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.threadpool_executor, self.__exit__)


class IndexDb:
    etcd_timeout_sec = 5
    etcd_lock_ttl_sec = 60

    def __init__(
        self,
        settings: IndexDbSettings,
        notif_channel: BotChannel = None,
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
        self.tg_user_queue = asyncio.Queue(maxsize=10000)
        self.notif_channel = notif_channel

        logger.warning("Initializing etcd clients... %s", str(self.settings.etcd_hosts))
        self.etcd_clients = [
            etcd3.client(host=x.split(":")[0],
                         port=x.split(":")[1] if len(x.split(":")) == 2 else 2379,
                         ca_cert=self.settings.etcd_cacert,
                         cert_cert=self.settings.etcd_cert,
                         cert_key=self.settings.etcd_key,
                         timeout=self.etcd_timeout_sec,
                         )
            for x in self.settings.etcd_hosts
        ]

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
        self.collections_id: dict[int, CollectionTaskData] = {}
        self.tasks = {
            'event_processor': self.loop.create_task(self.event_processor()),
            'nft_task_processor': self.loop.create_task(self.nft_task_processor()),
        }

        # running tasks
        for c in self.collection_config.collections:
            data = CollectionTaskData(c, instance=self.sync_collection_upsert(c))
            self.collections[c.b64url] = data
            self.indexer_tasks[c.b64url] = self.loop.create_task(self.nft_indexer(data))
            data.instance = self.sync_collection_upsert(c)
            self.collections_id[data.instance.id] = data

    async def shutdown(self):
        await self.tg_user_queue.join()
        for task in self.indexer_tasks.values():
            task.cancel()
        await asyncio.wait(self.indexer_tasks.values())

        for task in self.tasks.values():
            task.cancel()
        await asyncio.wait(self.tasks.values())

        self.threadpool_executor.shutdown()

    def setup_cache(self):
        self.collection_query = self.cache_manager.cached(expire=60)(self.collection_query)
        self.collection_random_feed = self.cache_manager.cached(expire=600)(self.collection_random_feed)

    async def register_tg_user(self, owner: str, user_id: int, username: str = None, is_premium: bool = False, country: str = None, language: str = None):
        self.tg_user_queue.put_nowait(TgUser(owner=owner, user_id=user_id,
                                             username=username[:40] if username else None,
                                             is_premium=is_premium,
                                             country=(country or "")[:2].lower(),
                                             language=(language or "")[:2].lower()
                                             ))

    async def event_processor(self):
        logger.warning("Event Processor task entering main loop")
        while True:
            try:
                await asyncio.sleep(1)

                await self.process_tg_queue(maxsize=100)

            except asyncio.CancelledError:
                logger.info("Event Processor task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception(
                    "Event Processor task got unhandled exception, sleep for %d", self.restart_timeout
                )
                await asyncio.sleep(self.restart_timeout)

    async def nft_task_processor(self):
        logger.warning("NFT scheduled task processor task entering main loop")
        while True:
            try:
                await asyncio.sleep(3)

                tasks, nfts, tgusers = await self.loop.run_in_executor(
                    self.threadpool_executor, self.sync_nft_task_get, 10
                )

                for task in tasks:
                    nft = nfts.get(task.pet_memory_nft_id)
                    if nft is None:
                        continue
                    user = tgusers.get(nft.owner)
                    if user is None:
                        continue
                    collection = self.collections_id.get(nft.collection_id).instance

                    if task.task_type == NftTaskType.NOTIFY_MINT:
                        await self.notif_channel.send_ntf_preview(nft, collection, user)
                        await self.notif_channel.send_ntf_mint(nft, collection, user, keyboard=True)
                    if task.task_type in [NftTaskType.NOTIFY_WARNING, NftTaskType.NOTIFY_EXPIRED]:
                        # TODO Update NFT from blockchain
                        await self.notif_channel.send_nft_storage_warning(nft, collection, user, keyboard=True)
            except asyncio.CancelledError:
                logger.info("NFT scheduled processor task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception(
                    "NFT scheduled processor task got unhandled exception, sleep for %d", self.restart_timeout
                )
                await asyncio.sleep(self.restart_timeout)

    async def nft_indexer(self, data: CollectionTaskData):
        address = data.nft_collection.b64url
        meas: CollectionMeasurement = self.stats[StatisticTags(address)]
        logger.warning("[%s]: Indexer task entering main loop", address)
        while True:
            try:
                await asyncio.sleep(self.settings.indexer_timeout)
                if self.tonlib is None:
                    continue
                if sum([1 for x in self.tonlib.get_workers_state().values() if x["is_sync"]]) == 0:
                    logger.warning("[%s]: No active Tonlib workers", address)
                    continue

                async with EtcdPoolLock(f'indexer:{address}', self.etcd_clients, self.threadpool_executor, self.etcd_lock_ttl_sec):
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
                                bulk.append(PetMemoryNft.from_nftmodel(collection_id=data.instance.id, data=nft_data))
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
            except (TonlibException, asyncio.TimeoutError, EtcdLockError) as E:
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

    async def collection_nft_make_icon(self, instance: PetMemoryNft):
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
            logger.warning("NFT icons convert error, address: %s - %s: %s", instance.address, type(E).__name__, E)
            return False
        return True

    async def collection_nft_make_icons(self, instances: list[PetMemoryNft]):
        sem = asyncio.Semaphore(self.settings.max_parallel_task)

        async def _sem_wrapper(instance: PetMemoryNft):
            async with sem:
                await self.collection_nft_make_icon(instance)

        tasks = [_sem_wrapper(x) for x in instances]
        await asyncio.gather(*tasks)

    def sync_tg_user_bulk_upsert(self, bulk: list[TgUser]):
        count = 0
        with Session(self.dbengine) as session:
            for user in bulk:
                try:
                    ex_user = session.exec(select(TgUser).where(TgUser.owner == user.owner and TgUser.user_id == user.user_id)).one()
                except NoResultFound:
                    pass

                try:
                    session.add(user)
                    count += 1
                except SQLAlchemyError as E:
                    logger.warning("User record writing error %s: %s", type(E).__name__, E)
                    pass
            session.commit()
            logger.info("Writren %d User records into TgUser", count)

    async def process_tg_queue(self, maxsize: int = 100):
        bulk: list[TgUser] = []
        index = set()
        while len(bulk) < maxsize and not self.tg_user_queue.empty():
            item = self.tg_user_queue.get_nowait()
            aggkey = (item.owner, item.user_id)
            if aggkey not in index:
                index.add(aggkey)
                bulk.append(item)
        logger.info("Read %d unique User records from qeueue", len(bulk))
        await self.loop.run_in_executor(
            self.threadpool_executor, self.sync_tg_user_bulk_upsert, bulk
        )

    def sync_nft_task_get(self, maxsize: int = 100):
        curr_time = datetime.datetime.now(datetime.timezone.utc)
        with Session(self.dbengine) as session:
            tasks = session.exec(
                select(NftTaskQueue).where(NftTaskQueue.task_time <= curr_time).with_for_update(skip_locked=True).limit(maxsize)
            ).all()

            ids = [x.pet_memory_nft_id for x in tasks]

            ex_tasks = [copy.deepcopy(x) for x in tasks]

            for item in tasks:
                session.delete(item)
            session.commit()
            nfts = session.exec(select(PetMemoryNft).where(PetMemoryNft.id.in_(ids))).all()
            owners = {x.owner for x in nfts}

            tgusers = session.exec(select(TgUser).where(TgUser.owner.in_(owners))).all()

        return ex_tasks, {x.id: x for x in nfts}, {x.owner: x for x in tgusers}

    def sync_collection_nft_bulk_insert(self, instance: PetsCollection, bulk: list[PetMemoryNft]):
        curr_time = datetime.datetime.now(datetime.timezone.utc)
        warn_offset = datetime.timedelta(days=10)
        expired_offset = datetime.timedelta(days=1)

        notifs = []
        with Session(self.dbengine) as session:
            # 1. Add NFTs
            session.add_all(bulk)
            session.flush()

            # 2. Add NFT Notifications
            for nft_instance in bulk:
                session.refresh(nft_instance)
                if nft_instance.fee_due_time is not None:
                    due_time = datetime.datetime.fromtimestamp(nft_instance.fee_due_time, tz=datetime.timezone.utc)
                    if due_time < curr_time:
                        continue
                    notifs += [
                        NftTaskQueue(
                            task_time=curr_time,
                            collection_id=instance.id,
                            task_type=NftTaskType.NOTIFY_MINT,
                            pet_memory_nft_id=nft_instance.id,
                            index=nft_instance.index,
                        ),
                        NftTaskQueue(
                            task_time=due_time - (warn_offset if due_time - warn_offset > curr_time else expired_offset),
                            collection_id=instance.id,
                            task_type=NftTaskType.NOTIFY_WARNING if due_time - warn_offset > curr_time else NftTaskType.NOTIFY_EXPIRED,
                            pet_memory_nft_id=nft_instance.id,
                            index=nft_instance.index,
                        )
                    ]
            session.add_all(notifs)

            # 2. Update Collection
            session.add(instance)
            session.commit()
            session.refresh(instance)

    def sync_collection_upsert(self, collection: CollectionInstance) -> PetsCollection:
        with Session(self.dbengine) as session:
            try:
                instance = session.exec(select(PetsCollection).where(PetsCollection.address == collection.b64url)).one()
            except NoResultFound:
                instance = None
            if instance is None:
                instance = PetsCollection(address=collection.b64url, index=0)
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

        result = await self.loop.run_in_executor(self.threadpool_executor, _warped_func, kwargs)
        return [x.to_nftheader(self.collections_id.get(x.collection_id).nft_collection.b64url, icon_size=icon_size) for x in result]

    def sync_collection_random_feed(self, limit: int = 100, **kwargs):
        segment_size = 1 << math.ceil(math.log2(limit)) + 1
        result: Sequence[PetMemoryNft] = []
        with Session(self.dbengine) as session:
            last_item = session.exec(select(PetMemoryNft).order_by(PetMemoryNft.id.desc())).first()
            last_id = last_item.id if last_item is not None else 0
            segment_count = last_id // segment_size
            n = round(random.random() * segment_count)
            x0 = p0 = segment_size * n
            x1 = p1 = p0 + segment_size

            select_stmt = select(PetMemoryNft).where(PetMemoryNft.error_time == None)  # noqa: E711
            for col, value in kwargs.items():
                if value is not None:
                    select_stmt = select_stmt.where(getattr(PetMemoryNft, col) == value)

            # segment tree climbing
            while len(result) < segment_size:
                result += session.exec(
                    select_stmt.where(PetMemoryNft.id >= x0).where(PetMemoryNft.id < x1).limit(segment_size - len(result))
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

        result = await self.loop.run_in_executor(self.threadpool_executor, _warped_func, kwargs)
        return [x.to_nftheader(self.collections_id.get(x.collection_id).nft_collection.b64url, icon_size=icon_size) for x in result]
