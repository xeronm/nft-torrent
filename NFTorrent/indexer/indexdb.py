import asyncio
import copy
import datetime
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
import etcd3
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import status
from pytonlib import TonlibException
from sqlalchemy.exc import NoResultFound, SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, delete, select, update

from NFTorrent.bot import BotApp, StatisticsMiddleware, services
from NFTorrent.bot.handlers import routers
from NFTorrent.cache import BaseCacheManager, DisabledCacheManager
from NFTorrent.dbmodels import NftTaskQueue, NftTaskType, PetMemoryNft, PetsCollection, TgUser
from NFTorrent.imageutils import convert_image
from NFTorrent.ipfs import IpfsRpcManager
from NFTorrent.models import CollectionData, NftItemData
from NFTorrent.modelsbase import CollectionConfig, CollectionInstance, MeasurementStore, StatisticNoTags
from NFTorrent.settings import IndexDbSettings
from NFTorrent.tonlib import TonlibContractIsNotNft, TonlibManager, TonlibRequestError
from NFTorrent.utils import parse_ipfs_uri, uri_ipfs, uri_supported

logger = logging.getLogger(__name__)
task_queue_logger = logging.getLogger("NFTorrent.TaskQueue")


@dataclass(frozen=True)
class StatisticTags:
    address: str


@dataclass
class CollectionMeasurement:
    db_next_index: int = 0
    bc_next_index: int = 0
    nft_index_count: int = 0
    nft_index_errors: int = 0
    last_checked: int = 0
    updated_time: int = 0
    task_enqueued: int = 0
    task_processed: int = 0
    nft_sync_updates: int = 0
    nft_sync_deletes: int = 0
    nft_updates: int = 0
    nft_deletes: int = 0
    nft_update_errors: int = 0
    nft_notif_storage: int = 0
    nft_notif_mints: int = 0
    nft_notif_updates: int = 0


@dataclass
class IndexerMeasurement:
    tg_user_queue_adds: int = 0
    tg_user_queue_gets: int = 0
    tg_user_creates: int = 0
    tg_user_create_errors: int = 0
    dp_active: int = 0
    dp_poll_time: int = 0
    dp_lock_failures: int = 0
    dp_task_failures: int = 0


@dataclass
class CollectionTaskData:
    nft_collection: CollectionInstance
    collection_data: CollectionData = None
    instance: PetsCollection = None
    meas: CollectionMeasurement = None


class EtcdLockError(Exception):
    pass


class EtcdPoolLock:

    def __init__(
        self,
        lock_name: str,
        etcd_clients: list[etcd3.Etcd3Client],
        threadpool_executor: ThreadPoolExecutor,
        lock_ttl: int = 60,
        loop: asyncio.BaseEventLoop | None = None,
    ):
        self.lock_name = lock_name
        self.lock_ttl = lock_ttl
        self.etcd_clients = etcd_clients
        self.threadpool_executor = threadpool_executor
        self._lock: etcd3.Lock = None
        self.loop = loop or asyncio.get_running_loop()

    def __enter__(self):
        if not self.etcd_clients:
            raise EtcdLockError("No etcd clients")

        for etcd in self.etcd_clients:
            try:
                etcd.status()
                lock = etcd.lock(name=self.lock_name, ttl=self.lock_ttl)
                if lock.acquire():
                    self._lock = lock
                    logger.info('etcd lock "%s" acquired uuid=%s', self.lock_name, self._lock.uuid)
                    return self
            except etcd3.Etcd3Exception as E:
                logger.info('etcd lock "%s", peer: %s error - %s: %s', self.lock_name, etcd._url, type(E).__name__, E)
                pass
        logger.info('etcd lock "%s" failed to acquire', self.lock_name)
        raise EtcdLockError("Unable to acquire Lock")

    def __exit__(self):
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    async def __aenter__(self):
        await self.loop.run_in_executor(self.threadpool_executor, self.__enter__)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.loop.run_in_executor(self.threadpool_executor, self.__exit__)

    async def refresh(self):
        if self._lock is None:
            raise EtcdLockError("Lock is not acquired")
        lease_info = await self.loop.run_in_executor(self.threadpool_executor, self._lock.refresh)
        if not lease_info or lease_info[0].TTL is None or lease_info[0].TTL <= 0:
            raise EtcdLockError("Lock refresh failed")
        return lease_info[0]

    async def lease_info(self):
        if self._lock is None:
            raise EtcdLockError("Lock is not acquired")
        return await self.loop.run_in_executor(self.threadpool_executor, self._lock.lease._get_lease_info)

    async def refresh_loop(self):
        try:
            ttl = (await self.lease_info()).TTL
            while True:
                await asyncio.sleep(ttl * 0.75)
                ttl = (await self.refresh()).TTL
        except Exception as E:
            logger.warning('etcd lock "%s", refresh error - %s: %s', self.lock_name, type(E).__name__, E)
            raise


class IndexDb:
    etcd_timeout_sec = 5
    etcd_lock_ttl_sec = 60
    warn_offset = datetime.timedelta(days=10)
    expired_offset = datetime.timedelta(days=1)
    nft_mutable_attributes = ["owner", "uri", "image", "image_data", "fee_due_time", "description"]
    nft_image_attributes = {"image", "image_data"}
    task_queue_timeout_sec = 3

    def __init__(
        self,
        settings: IndexDbSettings,
        bot_app: BotApp = None,
        bot_polling: bool = True,
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
        self.stats = MeasurementStore("NFTorrentIndexer", IndexerMeasurement)
        self.stats_coll = MeasurementStore("NFTorrentIndexerColl", CollectionMeasurement)
        self.collection_config = collection_config
        self.cache_manager = cache_manager or DisabledCacheManager()
        self.tg_user_queue = asyncio.Queue(maxsize=10000)
        self.bot_app = bot_app

        logger.warning("Initializing etcd clients... %s", str(self.settings.etcd_hosts))
        self.etcd_clients = [
            etcd3.client(
                host=x.split(":")[0],
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

        logger.warning("Starting... workers: %d", self.num_workers)
        self.threadpool_executor = ThreadPoolExecutor(max_workers=max(32, self.num_workers))

        # workers spawn
        self.loop = loop or asyncio.get_running_loop()
        self.collections: dict[str, CollectionTaskData] = {}
        self.collections_id: dict[int, CollectionTaskData] = {}
        self.tasks = {
            "initialize_db": self.loop.create_task(self.initialize_db()),
        }

        self.dp = None
        self.dp_active = False
        if self.bot_app:
            self.tasks["check_dbstats"] = self.loop.create_task(self.bot_app.backend.check_dbstats())
            if bot_polling:
                self.dp = Dispatcher(storage=MemoryStorage())
                self.dp.include_routers(*routers)

                self.dp.message.middleware(StatisticsMiddleware(stats_store=self.bot_app.stats))
                self.dp.callback_query.middleware(StatisticsMiddleware(stats_store=self.bot_app.stats))

                logger.warning(
                    "Bot polling task intialized... bot_id: %s",
                    self.bot_app.bot_id,
                )
            else:
                logger.warning("Bot poling task won`t start, since bot_polling: %s", bot_polling)

            if self.settings.task_queue_bulk_size:
                self.tasks["nft_task_processor"] = self.loop.create_task(self.nft_task_processor())
            else:
                logger.warning(
                    "NFT scheduled task processor won`t start, since task_queue_bulk_size: %s",
                    self.settings.task_queue_bulk_size,
                )
        else:
            logger.warning(
                "BotApp not provided, NFT scheduled task processor and Bot polling task won`t start.",
            )

    async def run_post_dbinit_task(self):
        self.tasks["event_processor"] = self.loop.create_task(self.event_processor())
        if self.bot_app:
            self.tasks["check_dbstats"] = self.loop.create_task(self.bot_app.backend.check_dbstats())
        if self.dp:
            self.tasks["bot_polling"] = self.loop.create_task(self.bot_polling())

        for address, data in self.collections.items():
            self.indexer_tasks[address] = self.loop.create_task(self.nft_indexer(data))

    async def initialize_db(self):
        while True:
            try:
                await self.loop.run_in_executor(self.threadpool_executor, SQLModel.metadata.create_all, self.dbengine)

                for c in self.collection_config.collections:
                    instance = await self.loop.run_in_executor(self.threadpool_executor, self.sync_collection_upsert, c.b64url)
                    data = CollectionTaskData(c, instance=instance)
                    data.meas = self.stats_coll[StatisticTags(c.b64url)]
                    self.collections[c.b64url] = data
                    self.collections_id[data.instance.id] = data

                break
            except SQLAlchemyError as E:
                logger.warning("DB initialization error: %s - %s", type(E).__name__, str(E))
                await asyncio.sleep(self.restart_timeout)
            except asyncio.CancelledError:
                logger.info("Initialize DB task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception("Initialize DB got unhandled exception, sleep for %d sec", self.restart_timeout)
                await asyncio.sleep(self.restart_timeout)

        logger.info('DB initialization completed, continue startup')
        await self.run_post_dbinit_task()

    async def event_processor(self):
        logger.warning("Event Processor task entering main loop")
        while True:
            try:
                await asyncio.sleep(self.task_queue_timeout_sec)

                await self.process_tg_queue(maxsize=100)

            except asyncio.CancelledError:
                logger.info("Event Processor task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception("Event Processor task got unhandled exception, sleep for %d sec", self.restart_timeout)
                await asyncio.sleep(self.restart_timeout)

    async def nft_task_processor(self):
        logger.warning("NFT scheduled task processor task entering main loop")
        while True:
            try:
                await asyncio.sleep(self.task_queue_timeout_sec)

                tasks, nfts, tgusers = await self.loop.run_in_executor(
                    self.threadpool_executor, self.sync_nft_task_get, self.settings.task_queue_bulk_size
                )
                if not len(tasks):
                    continue

                nfts_to_update = [
                    nfts[t.pet_memory_nft_id]
                    for t in tasks
                    if t.pet_memory_nft_id in nfts and t.task_type in [NftTaskType.NOTIFY_DUE_DATE, NftTaskType.SYNC]
                ]
                nft_updates, nft_tasks = await self.nft_update(nfts_to_update)

                for task in tasks:
                    coldata = self.collections_id.get(task.collection_id)
                    coldata.meas.task_processed += 1
                    collection = coldata.instance
                    logger.info(
                        "Process task task_id: %s, type: %d, collection: %s, index: %d",
                        task.id,
                        task.task_type,
                        collection.address,
                        task.index,
                    )

                    nft = nfts.get(task.pet_memory_nft_id)
                    if nft is None:
                        task_queue_logger.warning(
                            "nft task skipped (nft not found) - task_id: %s, type: %d, collection: %s, index: %d",
                            task.id,
                            task.task_type,
                            collection.address,
                            task.index,
                        )
                        continue

                    if getattr(nft, "_nft_update_error", None) is not None:
                        task_queue_logger.warning(
                            "nft task skipped (nft update error) - task_id: %s, type: %d, collection: %s, index: %d - %s: %s",
                            task.id,
                            task.task_type,
                            collection.address,
                            task.index,
                            type(nft._nft_update_error).__name__,
                            nft._nft_update_error,
                        )
                        continue

                    user = tgusers.get(nft.owner)
                    if user is None:
                        task_queue_logger.warning(
                            "nft task skipped (user not found) - task_id: %s, type: %d, collection: %s, index: %d, nft: %s",
                            task.id,
                            task.task_type,
                            collection.address,
                            task.index,
                            nft.address,
                        )
                        continue

                    if task.task_type == NftTaskType.NOTIFY_DUE_DATE:
                        curr_time = datetime.datetime.now(datetime.timezone.utc)
                        due_time = datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc)
                        if (
                            nft.last_notified
                            and nft.last_notified > curr_time - (self.warn_offset - self.expired_offset) / 2
                        ):
                            task_queue_logger.warning(
                                "nft task skipped (frequent due date notification) - task_id: %s, type: %d, collection: %s, index: %d, nft: %s",
                                task.id,
                                task.task_type,
                                collection.address,
                                task.index,
                                nft.address,
                            )
                            continue
                        elif due_time > curr_time + self.warn_offset:
                            task_queue_logger.warning(
                                "nft task skipped (due date greater than warn_offset) - task_id: %s, type: %d, collection: %s, index: %d, nft: %s",
                                task.id,
                                task.task_type,
                                collection.address,
                                task.index,
                                nft.address,
                            )
                            continue
                        else:
                            coldata.meas.nft_notif_storage += 1
                            await services.nft.notify_nft_storage_warning(
                                self.bot_app, nft, collection, user, keyboard=True
                            )
                            nft.last_notified = curr_time
                    if task.task_type == NftTaskType.NOTIFY_MINT:
                        coldata.meas.nft_notif_mints += 1
                        await services.nft.nft_preview(self.bot_app, nft, collection, user)
                        await services.nft.notify_nft_minted(self.bot_app, nft, collection, user, keyboard=True)
                    if task.task_type in [NftTaskType.NOTIFY_UPDATED, NftTaskType.NOTIFY_TRANSFERED]:
                        coldata.meas.nft_notif_updates += 1
                        await services.nft.nft_preview(self.bot_app, nft, collection, user)
                        await services.nft.notify_nft_updated(
                            self.bot_app,
                            nft,
                            collection,
                            user,
                            keyboard=True,
                            transfered=(task.task_type == NftTaskType.NOTIFY_TRANSFERED),
                        )

                    task_queue_logger.info(
                        "nft task done - task_id: %s, type: %d, collection: %s, index: %d, nft: %s",
                        task.id,
                        task.task_type,
                        collection.address,
                        task.index,
                        nft.address,
                    )

                await self.loop.run_in_executor(
                    self.threadpool_executor, self.sync_collection_nft_bulk_update, nft_updates, tasks, nft_tasks
                )
            except asyncio.CancelledError:
                logger.info("NFT scheduled processor task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception(
                    "NFT scheduled processor task got unhandled exception, sleep for %d sec", self.restart_timeout
                )
                await asyncio.sleep(self.restart_timeout)

    async def bot_polling(self):
        logger.warning("Bot polling task entering main loop")
        lock_name = f"bot:{self.bot_app.bot_id}"
        meas: IndexerMeasurement = self.stats[StatisticNoTags]

        while True:
            try:
                async with EtcdPoolLock(
                    lock_name,
                    self.etcd_clients,
                    threadpool_executor=self.threadpool_executor,
                    lock_ttl=self.etcd_lock_ttl_sec,
                    loop=self.loop,
                ) as lock:
                    logger.warning('Bot polling task: Lock "%s" acquired, Entering start_polling...', lock_name)

                    pooling = asyncio.create_task(self.dp.start_polling(self.bot_app.bot, handle_signals=False))
                    refresh = asyncio.create_task(lock.refresh_loop())
                    self.dp_active = True
                    meas.dp_active = 1
                    meas.dp_poll_time = int(time.time())
                    try:
                        done, pending = await asyncio.wait([pooling, refresh], return_when=asyncio.FIRST_COMPLETED)
                        if pooling in done and pooling.exception():
                            meas.dp_task_failures += 1
                            exc = pooling.exception()
                            logger.warning(
                                "Bot polling task: polling terminated with error - %s: %s", type(exc).__name__, exc
                            )
                        else:
                            logger.warning("Bot polling task: polling exited")
                        if refresh in done and refresh.exception():
                            meas.dp_lock_failures += 1
                            exc = refresh.exception()
                            logger.warning(
                                "Bot polling task: lock refresh task terminated with error - %s: %s",
                                type(exc).__name__,
                                exc,
                            )
                    finally:
                        self.dp_active = False
                        meas.dp_active = 0
                        meas.dp_poll_time = 0
                        pooling.cancel()
                        refresh.cancel()
                        await asyncio.gather(pooling, refresh, return_exceptions=True)

                await asyncio.sleep(self.restart_timeout)
            except (EtcdLockError, etcd3.Etcd3Exception) as E:
                logger.info("Bot polling task: lock error: %s", type(E).__name__)
                await asyncio.sleep(self.restart_timeout)
            except asyncio.CancelledError:
                logger.info("Bot polling task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception("Bot polling task got unhandled exception, sleep for %d sec", self.restart_timeout)
                await asyncio.sleep(self.restart_timeout)

    async def nft_indexer(self, data: CollectionTaskData):
        address = data.nft_collection.b64url
        logger.warning("[%s]: Indexer task entering main loop", address)
        while True:
            try:
                await asyncio.sleep(self.settings.indexer_timeout)
                if self.tonlib is None:
                    continue
                if sum([1 for x in self.tonlib.get_workers_state().values() if x["is_sync"]]) == 0:
                    logger.warning("[%s]: No active Tonlib workers", address)
                    continue

                async with EtcdPoolLock(
                    f"indexer:{address}", self.etcd_clients, self.threadpool_executor, self.etcd_lock_ttl_sec
                ) as lock:
                    cycle = asyncio.create_task(self._nft_indexer_cycle(data))
                    refresh = asyncio.create_task(lock.refresh_loop())
                    try:
                        done, pending = await asyncio.wait([cycle, refresh], return_when=asyncio.FIRST_COMPLETED)
                        if refresh in done and refresh.exception():
                            exc = refresh.exception()
                            logger.warning(
                                "[%s]: lock refresh task terminated with error - %s: %s",
                                address,
                                type(exc).__name__,
                                exc,
                            )
                        if cycle in done and cycle.exception():
                            raise cycle.exception()
                    finally:
                        cycle.cancel()
                        refresh.cancel()
                        await asyncio.gather(cycle, refresh, return_exceptions=True)

            except (TonlibException, asyncio.TimeoutError, EtcdLockError, SQLAlchemyError) as E:
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
                    "[%s]: Indexer task got unhandled exception, sleep for %d sec", address, self.restart_timeout
                )
                await asyncio.sleep(self.restart_timeout)

    async def shutdown(self):
        if self.dp:
            try:
                await self.dp.stop_polling()
            except Exception:
                pass
        await self.tg_user_queue.join()
        for task in self.indexer_tasks.values():
            task.cancel()
        await asyncio.wait(self.indexer_tasks.values())

        for task in self.tasks.values():
            task.cancel()
        await asyncio.wait(self.tasks.values())

        self.threadpool_executor.shutdown()

    def setup_cache(self):
        self.nft_get = self.cache_manager.cached(expire=15)(self.nft_get)
        self.nft_list = self.cache_manager.cached(expire=15)(self.nft_list)
        self.collection_query = self.cache_manager.cached(expire=60)(self.collection_query)
        self.collection_random_feed = self.cache_manager.cached(expire=300)(self.collection_random_feed)

    async def register_tg_user(
        self,
        owner: str,
        user_id: int,
        username: str = None,
        is_premium: bool = False,
        country: str = None,
        language: str = None,
    ):
        self.stats[StatisticNoTags].tg_user_queue_adds += 1
        self.tg_user_queue.put_nowait(
            TgUser(
                owner=owner,
                user_id=user_id,
                username=username[:40] if username else None,
                is_premium=is_premium,
                country=(country or "")[:2].lower(),
                language=(language or "")[:2].lower(),
            )
        )

    def _nft_update(self, nft: PetMemoryNft, new_nft: PetMemoryNft, nft_notifs: list[NftTaskQueue]):
        curr_time = datetime.datetime.now(datetime.timezone.utc)
        nft._nft_updated = False
        nft._nft_image_updated = False
        nft._nft_transfered = False
        if nft.deleted_time is not None:
            logger.warning("looks like NFT was restored! address: %s", nft.address)
            nft._nft_updated = True
            nft.deleted_time = None

        for attr in self.nft_mutable_attributes:
            vold = getattr(nft, attr)
            vnew = getattr(new_nft, attr)
            if vold != vnew:
                setattr(nft, attr, vnew)
                nft._nft_updated = True
                if attr == "owner":
                    nft._nft_transfered = True
                if attr in self.nft_image_attributes:
                    nft._nft_image_updated = True

        if nft._nft_updated:
            nft.updated_time = curr_time
            nft_notifs.append(
                NftTaskQueue(
                    task_time=curr_time + datetime.timedelta(seconds=self.task_queue_timeout_sec),
                    collection_id=nft.collection_id,
                    task_type=NftTaskType.NOTIFY_TRANSFERED if nft._nft_transfered else NftTaskType.NOTIFY_UPDATED,
                    pet_memory_nft_id=nft.id,
                    index=nft.index,
                )
            )

        due_time = datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc)
        if due_time > curr_time:
            nft_notifs.append(
                NftTaskQueue(
                    task_time=due_time
                    - (self.warn_offset if due_time - self.warn_offset > curr_time else self.expired_offset),
                    collection_id=nft.collection_id,
                    task_type=NftTaskType.NOTIFY_DUE_DATE,
                    pet_memory_nft_id=nft.id,
                    index=nft.index,
                )
            )

    def sync_nft_get(self, address: str):
        nft = None
        with Session(self.dbengine) as session:
            try:
                nft = session.exec(select(PetMemoryNft).where(PetMemoryNft.address == address)).one()
                session.expunge(nft)
            except NoResultFound:
                pass
        return nft

    async def nft_get(self, address: str):
        return await self.loop.run_in_executor(self.threadpool_executor, self.sync_nft_get, address)

    def sync_nft_list(self, owner: str, offset: int = 0, limit: int = 20):
        with Session(self.dbengine) as session:
            return session.exec(
                select(PetMemoryNft)
                .where(PetMemoryNft.owner == owner)
                .order_by(PetMemoryNft.id)
                .offset(offset)
                .limit(limit)
            ).all()

    async def nft_list(self, owner: str, icon_size: str = None, offset: int = 0, limit: int = 20):
        result = await self.loop.run_in_executor(self.threadpool_executor, self.sync_nft_list, owner, offset, limit)
        return [
            x.to_nftheader(self.collections_id.get(x.collection_id).nft_collection.b64url, icon_size=icon_size)
            for x in result
            if x.collection_id in self.collections_id
        ]

    async def nft_update_nft_data(self, address: str, nft_data: NftItemData = None):
        # TODO: Shoud rewrite to queue and bulk operations
        nft = await self.nft_get(address)
        if nft is not None:
            if uri_ipfs(nft.image):
                prev_cid, _, _ = parse_ipfs_uri(nft.image)

        if nft_data is None:
            if nft is not None:
                if prev_cid:
                    await self.ipfs.nft_unlink(prev_cid, nft.address)
                cdata = self.collections_id.get(nft.collection_id)
                cdata.meas.nft_sync_deletes += 1
                nft.deleted_time = datetime.datetime.now(datetime.timezone.utc)
                await self.loop.run_in_executor(
                    self.threadpool_executor, self.sync_collection_nft_bulk_update, [nft], [], []
                )
            return

        cdata = self.collections.get(nft_data.collection_address)
        if cdata is None:
            return
        new_nft = PetMemoryNft.from_nftmodel(collection_id=cdata.instance.id, data=nft_data)

        if nft is None:
            nft = new_nft
            nft._nft_image_updated = True
            nft._nft_updated = True
        nft_notifs = []
        self._nft_update(nft, new_nft, nft_notifs)

        if nft._nft_image_updated:
            if uri_ipfs(nft.image):
                cid, _, _ = parse_ipfs_uri(nft.image)
                if prev_cid != cid:
                    await self.ipfs.nft_unlink(prev_cid, nft.address)

            if cid:
                torrent_info = await self.ipfs.get_cid_info(cid)
                nft.torrent_info = pickle.dumps(torrent_info)
            else:
                nft.torrent_info = None
            await self.collection_nft_make_icons([nft])
        elif nft.error_code is not None:
            nft._nft_updated = True
            await self.collection_nft_make_icons([nft])

        if nft._nft_updated:
            cdata.meas.nft_sync_updates += 1
            await self.loop.run_in_executor(
                self.threadpool_executor, self.sync_collection_nft_bulk_update, [nft], [], nft_notifs
            )

    async def nft_update(self, nfts: list[PetMemoryNft]) -> tuple[list[PetMemoryNft], list[NftTaskQueue]]:
        """
        Updates NFT instances with new data from blockchain and make apropriate tasks. Does not write data into DB.
        Returns:
            - update NFTs
            - created Tasks
        """
        nft_updates = []
        nft_notifs = []
        for nft in nfts:
            logger.info("Updating NFT address: %s", nft.address)
            nft._nft_update_error = None
            cdata = self.collections_id.get(nft.collection_id)
            try:
                nft_data = None
                try:
                    nft_data = await self.tonlib.get_nft_data(nft.address, skip_verification=True)
                except TonlibContractIsNotNft:
                    account_state = await self.tonlib.generic_get_account_state(nft.address)
                    if account_state["account_state"]["@type"] != "uninited.accountState":
                        raise

                if nft_data is None:
                    cdata.meas.nft_deletes += 1
                    nft.deleted_time = datetime.datetime.now(datetime.timezone.utc)
                    nft_updates.append(nft)
                else:
                    new_nft = PetMemoryNft.from_nftmodel(collection_id=nft.collection_id, data=nft_data)
                    self._nft_update(nft, new_nft, nft_notifs)
                    if nft._nft_updated:
                        cdata.meas.nft_updates += 1
                        nft_updates.append(nft)
            except TonlibRequestError as E:
                logger.info("Updating NFT address: %s, got error - %s: %s", nft.address, type(E).__name__, E)
                nft._nft_update_error = E
                cdata.meas.nft_update_errors += 1

        await self.collection_nft_make_icons([x for x in nft_updates if x._nft_image_updated])
        return nft_updates, nft_notifs

    async def _nft_indexer_cycle(self, data: CollectionTaskData):
        address = data.nft_collection.b64url
        logger.info("[%s]: Updating collection info...", address)
        # Refresh data from DB
        data.instance = await self.loop.run_in_executor(
            self.threadpool_executor, self.sync_collection_upsert, data.nft_collection.b64url
        )
        data.meas.db_next_index = data.instance.index

        # Refresh data from TON
        data.collection_data = await self.tonlib.get_collection_data(address)
        next_index = data.collection_data.next_item_index
        data.meas.bc_next_index = next_index
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
                    instance = PetMemoryNft.from_nftmodel(collection_id=data.instance.id, data=nft_data)
                    if uri_ipfs(instance.image):
                        cid, _, _ = parse_ipfs_uri(instance.image)
                        if cid:
                            torrent_info = await self.ipfs.get_cid_info(cid)
                            instance.torrent_info = pickle.dumps(torrent_info)

                    bulk.append(instance)
                except TonlibRequestError as E:
                    data.meas.nft_index_errors += 1
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
                notifs_count = await self.loop.run_in_executor(
                    self.threadpool_executor, self.sync_collection_nft_bulk_insert, data.instance, bulk
                )
                data.meas.task_enqueued += notifs_count
                data.meas.nft_index_count += len(bulk)
                data.meas.updated_time = int(time.time())
                data.meas.db_next_index = data.instance.index

        data.meas.last_checked = int(time.time())

    async def collection_nft_make_icon(self, instance: PetMemoryNft):
        buffer = None
        instance.error_time = None
        instance.error_code = None
        if instance.image and uri_supported(instance.image):
            logger.info(
                "Getting image for NFT icons, address: %s, uri: %s",
                instance.address,
                instance.image,
            )
            try:
                if uri_ipfs(instance.image):
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
                convert_image,
                buffer,
                self.settings.icon_size_small,
                self.settings.icon_format,
            )
            medium = await self.loop.run_in_executor(
                self.threadpool_executor,
                convert_image,
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
        creates = errors = 0
        with Session(self.dbengine) as session:
            for user in bulk:
                ex_user = None
                try:
                    ex_user = session.exec(
                        select(TgUser).where(TgUser.owner == user.owner and TgUser.user_id == user.user_id)
                    ).one()
                except NoResultFound:
                    pass
                if ex_user:
                    continue

                try:
                    session.add(user)
                    creates += 1
                except SQLAlchemyError as E:
                    logger.warning("TgUser Queue: User record writing error %s: %s", type(E).__name__, E)
                    errors += 1
                    pass
            session.commit()
            self.stats[StatisticNoTags].tg_user_creates += creates
            self.stats[StatisticNoTags].tg_user_create_errors += errors
            logger.info("TgUser Queue: Writren %d User records, errors: %s", creates, errors)

    async def process_tg_queue(self, maxsize: int = 100):
        bulk: list[TgUser] = []
        index = set()
        while len(bulk) < maxsize and not self.tg_user_queue.empty():
            item = self.tg_user_queue.get_nowait()
            aggkey = (item.owner, item.user_id)
            if aggkey not in index:
                index.add(aggkey)
                bulk.append(item)

        logger.info("TgUser Queue: Read %d unique User records", len(bulk))
        self.stats[StatisticNoTags].tg_user_queue_gets += len(bulk)
        if len(bulk):
            await self.loop.run_in_executor(self.threadpool_executor, self.sync_tg_user_bulk_upsert, bulk)

    def sync_nft_task_get(self, maxsize: int = 100):
        curr_time = datetime.datetime.now(datetime.timezone.utc)
        with Session(self.dbengine) as session:
            tasks = session.exec(
                select(NftTaskQueue)
                .where(NftTaskQueue.task_time <= curr_time)
                .with_for_update(skip_locked=True)
                .limit(maxsize)
            ).all()

            if not tasks:
                return [], {}, {}

            ids = [x.id for x in tasks]
            nft_ids = [x.pet_memory_nft_id for x in tasks]
            ex_tasks = [copy.deepcopy(x) for x in tasks]

            # UPDATE SET procst_time = sysdate AND task_time = Null
            nfts = session.exec(
                update(NftTaskQueue)
                .where(NftTaskQueue.id.in_(ids))
                .values(procst_time=curr_time, task_time=None)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            logger.info("NFT TaskQueue: Read %d tasks from queue", len(ex_tasks))

            nfts = session.exec(select(PetMemoryNft).where(PetMemoryNft.id.in_(nft_ids))).all()
            owners = {x.owner for x in nfts}
            tgusers = session.exec(select(TgUser).where(TgUser.owner.in_(owners))).all()

        return ex_tasks, {x.id: x for x in nfts}, {x.owner: x for x in tgusers}

    def sync_collection_nft_bulk_update(
        self, nft_updates: list[PetMemoryNft], comp_tasks: list[NftTaskQueue], new_tasks: list[NftTaskQueue]
    ):
        with Session(self.dbengine) as session:
            # Delete completed tasks
            logger.info("NFT TaskQueue: Delete %d tasks from queue", len(comp_tasks))
            session.exec(
                delete(NftTaskQueue).where(
                    (NftTaskQueue.id.in_([x.id for x in comp_tasks])) & (NftTaskQueue.task_time.is_(None))
                )
            )

            # Update NFTs
            for nft_instance in nft_updates:
                session.merge(nft_instance)

            # Insert new tasks
            # TODO: check existing task
            logger.info("NFT TaskQueue: Create %d tasks", len(new_tasks))
            session.add_all(new_tasks)
            session.commit()

    def sync_collection_nft_bulk_insert(self, instance: PetsCollection, bulk: list[PetMemoryNft]):
        curr_time = datetime.datetime.now(datetime.timezone.utc)

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
                            task_time=curr_time + datetime.timedelta(seconds=self.task_queue_timeout_sec),
                            collection_id=instance.id,
                            task_type=NftTaskType.NOTIFY_MINT,
                            pet_memory_nft_id=nft_instance.id,
                            index=nft_instance.index,
                        ),
                        NftTaskQueue(
                            task_time=due_time
                            - (self.warn_offset if due_time - self.warn_offset > curr_time else self.expired_offset),
                            collection_id=instance.id,
                            task_type=NftTaskType.NOTIFY_DUE_DATE,
                            pet_memory_nft_id=nft_instance.id,
                            index=nft_instance.index,
                        ),
                    ]
            logger.info("NFT TaskQueue: Create %d tasks", len(notifs))
            session.add_all(notifs)

            # 2. Update Collection
            session.merge(instance)
            session.commit()
            return len(notifs)

    def sync_collection_upsert(self, address: str) -> PetsCollection:
        with Session(self.dbengine) as session:
            try:
                instance = session.exec(select(PetsCollection).where(PetsCollection.address == address)).one()
            except NoResultFound:
                instance = None
            if instance is None:
                instance = PetsCollection(address=address, index=0)
                session.add(instance)
                session.commit()
                session.refresh(instance)
        return instance

    def get_indexdb_state(self):
        return {
            "collections": [
                {"address": x.nft_collection.b64url, "blockchain": x.collection_data} for x in self.collections.values()
            ],
            "stats": (
                self.stats.as_list() + self.stats_coll.as_list() + self.bot_app.get_bot_state() if self.bot_app else []
            ),
        }

    def get_measurements(self, timestamp: int) -> list[str]:
        return (
            self.stats.as_influx(timestamp)
            + self.stats_coll.as_influx(timestamp)
            + self.bot_app.get_measurements(timestamp)
            if self.bot_app
            else []
        )

    def sync_collection_query(self, limit: int = 100, offset: int = None, **kwargs):
        with Session(self.dbengine) as session:
            select_stmt = select(PetMemoryNft).where(PetMemoryNft.error_time.is_(None))
            for col, value in kwargs.items():
                if value is not None:
                    select_stmt = select_stmt.where(getattr(PetMemoryNft, col) == value)

            if offset is not None:
                select_stmt = select_stmt.offset(offset)
            if limit is not None:
                select_stmt = select_stmt.limit(limit)
            return session.exec(select_stmt).all()

    async def collection_query(self, icon_size: str = None, **kwargs):

        def _warped_func(kwargs):
            return self.sync_collection_query(**kwargs)

        result = await self.loop.run_in_executor(self.threadpool_executor, _warped_func, kwargs)
        return [
            x.to_nftheader(self.collections_id.get(x.collection_id).nft_collection.b64url, icon_size=icon_size)
            for x in result
            if x.collection_id in self.collections_id
        ]

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

            select_stmt = select(PetMemoryNft).where(
                PetMemoryNft.error_time.is_(None) & PetMemoryNft.deleted_time.is_(None)
            )
            for col, value in kwargs.items():
                if value is not None:
                    select_stmt = select_stmt.where(getattr(PetMemoryNft, col) == value)

            # segment tree climbing
            while len(result) < segment_size:
                result += session.exec(
                    select_stmt.where(PetMemoryNft.id >= x0)
                    .where(PetMemoryNft.id < x1)
                    .limit(segment_size - len(result))
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
        return [
            x.to_nftheader(self.collections_id.get(x.collection_id).nft_collection.b64url, icon_size=icon_size)
            for x in result
            if x.collection_id in self.collections_id
        ]
