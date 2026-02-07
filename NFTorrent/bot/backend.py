import asyncio
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from aiogram.types import User
from sqlalchemy import distinct, func
from sqlmodel import Session, SQLModel, create_engine, select

from NFTorrent.cache import BaseCacheManager
from NFTorrent.dbmodels import NftTaskQueue, PetMemoryNft, PetsCollection, TgUser, UserInquiry
from NFTorrent.modelsbase import MeasurementStore, StatisticMeasurement, StatisticNoTags, with_stats

from .main import BackendForbidden, BackendInterface, BaseInquiry, NftListItem

logger = logging.getLogger(__name__)


@dataclass
class DbStats:
    users: int = 0
    wallets: int = 0
    inquiries: int = 0
    nfts: int = 0
    tasks: int = 0
    task_errors: int = 0


class Backend(BackendInterface):
    check_dbstats_timeout = 60

    def __init__(
        self,
        url: str,
        loop: asyncio.BaseEventLoop | None = None,
        threadpool_executor: ThreadPoolExecutor | None = None,
        cache_manager: BaseCacheManager | None = None,
        max_workers: int = 8,
    ):
        self.dbengine = create_engine(url)
        SQLModel.metadata.create_all(self.dbengine)
        self.loop = loop or asyncio.get_running_loop()
        self.threadpool_executor = threadpool_executor or ThreadPoolExecutor(max_workers=max_workers)
        self.cache_manager = cache_manager
        self._collection = {}
        self.stats = MeasurementStore("NFTorrentBotBackend", StatisticMeasurement)
        self.stats_db = MeasurementStore("NFTorrentBotBackendDb", DbStats)
        if cache_manager is not None:
            self.setup_cache()
        self._cached_dbstats = None

    async def check_dbstats(self):
        logger.warning("[check_dbstats]: Entering main loop")
        while True:
            try:
                try:
                    self.stats_db[StatisticNoTags] = await self.dbstats()
                except Exception as E:
                    logger.warning(
                        "[check_dbstats]: Failed to get node state - %s: %s",
                        type(E),
                        E,
                    )

                await asyncio.sleep(self.check_dbstats_timeout)
            except asyncio.CancelledError:
                logger.warning("[check_dbstats]: Task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception(
                    "[check_dbstats]: Unhandled exception, sleep for %d sec",
                    self.check_dbstats_timeout * 5,
                )
                await asyncio.sleep(self.check_dbstats_timeout * 5)

    def setup_cache(self):
        self.dbstats = with_stats(key="cached_dbstats", stats=self.stats)(
            self.cache_manager.cached(expire=30)(self.dbstats)
        )
        self.nft_list = with_stats(key="cached_nft_list", stats=self.stats)(
            self.cache_manager.cached(expire=30)(self.nft_list)
        )
        self.nft_get = with_stats(key="cached_nft_get", stats=self.stats)(
            self.cache_manager.cached(expire=30)(self.nft_get)
        )
        self.inquiry_get = with_stats(key="cached_inquiry_get", stats=self.stats)(
            self.cache_manager.cached(expire=15)(self.inquiry_get)
        )

    def sync_get_collection(self, collection_id: int):
        collection = self._collection.get(collection_id)
        if collection is None:
            with Session(self.dbengine) as session:
                collection = session.exec(select(PetsCollection).where(PetsCollection.id == collection_id)).one()
                session.expunge(collection)
                self._collection[collection_id] = collection
        return collection

    def sync_inquiry_list(self, user_id: int = None, offset: int = 0, limit: int = 20) -> list[BaseInquiry]:
        with Session(self.dbengine) as session:
            stmt = select(UserInquiry).where(UserInquiry.state.is_not(None))
            if user_id is not None:
                stmt = stmt.where(UserInquiry.user_id == user_id)

            items = [
                BaseInquiry(**x.model_dump())
                for x in session.exec(stmt.order_by(UserInquiry.id).offset(offset).limit(limit)).all()
            ]
        return items

    @with_stats()
    async def inquiry_list(self, user_id: int = None, offset: int = 0, limit: int = 20) -> list[BaseInquiry]:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(
                self.threadpool_executor, self.sync_inquiry_list, user_id, offset, limit
            )
        else:
            return self.sync_inquiry_list(user_id)

    def sync_inquiry_create(self, user: User, data) -> BaseInquiry:
        with Session(self.dbengine) as session:
            inquiry = UserInquiry(
                user_id=user.id,
                inquiry_id=data["inquiry_id"],
                is_premium=user.is_premium,
                language=user.language_code,
                username=user.username,
                subject=data["subject"],
                message=data["message"],
                message_id=data["message_id"],
                nft_address=data.get("nft_address"),
            )
            session.add(inquiry)
            session.commit()
            session.refresh(inquiry)
            return BaseInquiry(**inquiry.model_dump())

    @with_stats()
    async def inquiry_create(self, user, data) -> BaseInquiry:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_inquiry_create, user, data)
        else:
            return self.sync_inquiry_create(user, data)

    def sync_inquiry_close(
        self, inquiry_id: str, user_id: int = None, admin_user_id: int = None, admin_message: str = None
    ) -> BaseInquiry:
        with Session(self.dbengine) as session:
            inquiry = session.exec(
                select(UserInquiry).where(UserInquiry.inquiry_id == inquiry_id).with_for_update()
            ).one()

            if user_id is not None and inquiry.user_id != user_id:
                raise BackendForbidden("Not an Owner")
            if inquiry.state is None:
                raise BackendForbidden("Invalid state")

            curr_time = datetime.datetime.now(datetime.timezone.utc)
            inquiry.admin_user_id = admin_user_id if admin_user_id is not None else user_id
            inquiry.admin_message = admin_message
            inquiry.updated_time = curr_time
            inquiry.closed_time = curr_time
            inquiry.state = None
            base_inquiry = BaseInquiry(**inquiry.model_dump())
            session.commit()
            return base_inquiry

    @with_stats()
    async def inquiry_close(
        self, inquiry_id: str, user_id: int = None, admin_user_id: int = None, admin_message: str = None
    ) -> BaseInquiry:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(
                self.threadpool_executor, self.sync_inquiry_close, inquiry_id, user_id, admin_user_id, admin_message
            )
        else:
            return self.sync_inquiry_close(inquiry_id, user_id, admin_user_id, admin_message)

    def sync_inquiry_block(
        self, inquiry_id: str, admin_user_id: int = None, admin_message: str = None, disable_to_hours: int = None
    ) -> BaseInquiry:
        with Session(self.dbengine) as session:
            inquiry = session.exec(
                select(UserInquiry).where(UserInquiry.inquiry_id == inquiry_id).with_for_update()
            ).one()
            if inquiry.state is None:
                raise BackendForbidden("Invalid state")

            curr_time = datetime.datetime.now(datetime.timezone.utc)
            inquiry.admin_user_id = admin_user_id
            inquiry.admin_message = admin_message
            inquiry.updated_time = curr_time
            inquiry.disabled_to = curr_time + datetime.timedelta(hours=disable_to_hours)
            base_inquiry = BaseInquiry(**inquiry.model_dump())
            session.commit()
            return base_inquiry

    @with_stats()
    async def inquiry_block(
        self, inquiry_id: str, admin_user_id: int = None, admin_message: str = None, disable_to_hours: int = None
    ) -> BaseInquiry:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(
                self.threadpool_executor,
                self.sync_inquiry_block,
                inquiry_id,
                admin_user_id,
                admin_message,
                disable_to_hours,
            )
        else:
            return self.sync_inquiry_block(inquiry_id, admin_user_id, admin_message, disable_to_hours)

    def sync_inquiry_get(self, inquiry_id: str) -> BaseInquiry:
        with Session(self.dbengine) as session:
            inquiry = session.exec(select(UserInquiry).where(UserInquiry.inquiry_id == inquiry_id)).one()
            return inquiry

    @with_stats()
    async def inquiry_get(
        self, inquiry_id: str, admin_user_id: int = None, admin_message: str = None, disable_to_hours: int = None
    ) -> BaseInquiry:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_inquiry_get, inquiry_id)
        else:
            return self.sync_inquiry_get(inquiry_id)

    def sync_nft_list(self, user_id: int = None, offset: int = 0, limit: int = 20):
        with Session(self.dbengine) as session:
            owners = [x.owner for x in session.exec(select(TgUser).where(TgUser.user_id == user_id)).all()]

            nfts = [
                NftListItem(address=x.address, name=x.name, species=x.species, species_name=x.species_name)
                for x in session.exec(
                    select(PetMemoryNft)
                    .where(PetMemoryNft.owner.in_(owners) & PetMemoryNft.deleted_time.is_(None))
                    .order_by(PetMemoryNft.id)
                    .offset(offset)
                    .limit(limit)
                ).all()
            ]
            return owners, nfts

    @with_stats()
    async def nft_list(self, user_id: int = None, offset: int = 0, limit: int = 20):
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_nft_list, user_id, offset, limit)
        else:
            return self.sync_nft_list(user_id)

    def sync_nft_get(self, address: str = None):
        with Session(self.dbengine) as session:
            nft = session.exec(
                select(PetMemoryNft).where((PetMemoryNft.address == address) & PetMemoryNft.deleted_time.is_(None))
            ).one()
            session.expunge(nft)
            return nft, self.sync_get_collection(nft.collection_id)

    @with_stats()
    async def nft_get(self, address: str = None):
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_nft_get, address)
        else:
            return self.sync_nft_get(address)

    def sync_dbstats(self, address: str = None) -> DbStats:
        with Session(self.dbengine) as session:
            # users = session.exec(select(func.count()).select_from(TgUser)).scalar()
            nfts = session.exec(select(func.count()).select_from(PetMemoryNft)).one()
            inquiries = session.exec(
                select(func.count()).select_from(UserInquiry).where(UserInquiry.state.is_not(None))
            ).one()

            users = session.exec(
                select(
                    func.count(distinct(TgUser.user_id)).label("users"),
                    func.count(distinct(TgUser.owner)).label("wallets"),
                )
            ).one()

            tasks = session.exec(
                select(
                    func.count(NftTaskQueue.task_time).label("tasks"),
                    func.count(NftTaskQueue.procst_time).label("task_errors"),
                )
            ).one()

            return DbStats(
                users=users[0], wallets=users[1], inquiries=inquiries, nfts=nfts, tasks=tasks[0], task_errors=tasks[1]
            )

    @with_stats()
    async def dbstats(self) -> DbStats:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_dbstats)
        else:
            return self.sync_dbstats()
