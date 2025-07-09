import asyncio
import datetime
from concurrent.futures import ThreadPoolExecutor

from aiogram.types import User
from sqlmodel import Session, SQLModel, create_engine, select

from NFTorrent.dbmodels import PetMemoryNft, PetsCollection, TgUser, UserInquiry

from .main import BackendForbidden, BackendInterface, BaseInquiry, NftListItem


class Backend(BackendInterface):

    def __init__(
        self, url: str, loop: asyncio.BaseEventLoop | None = None, threadpool_executor: ThreadPoolExecutor | None = None
    ):
        self.dbengine = create_engine(url)
        SQLModel.metadata.create_all(self.dbengine)
        self.loop = loop or asyncio.get_running_loop()
        self.threadpool_executor = threadpool_executor or ThreadPoolExecutor(max_workers=4)
        self._collection = {}

    def sync_get_collection(self, collection_id: int):
        collection = self._collection.get(collection_id)
        if collection is None:
            with Session(self.dbengine) as session:
                collection = session.exec(select(PetsCollection).where(PetsCollection.id == collection_id)).one()
                session.expunge(collection)
                self._collection[collection_id] = collection
        return collection

    def sync_inquiry_list(self, user) -> list[BaseInquiry]:
        with Session(self.dbengine) as session:
            items = [
                BaseInquiry(**x.model_dump())
                for x in session.exec(
                    select(UserInquiry).where((UserInquiry.user_id == user.id) & (UserInquiry.state.is_not(None)))
                ).all()
            ]
        return items

    async def inquiry_list(self, user) -> list[BaseInquiry]:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_inquiry_list, user)
        else:
            return self.sync_inquiry_list(user)

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

            return BaseInquiry(**inquiry.model_dump())

    async def inquiry_get(
        self, inquiry_id: str, admin_user_id: int = None, admin_message: str = None, disable_to_hours: int = None
    ) -> BaseInquiry:
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_inquiry_get, inquiry_id)
        else:
            return self.sync_inquiry_get(inquiry_id)

    def sync_nft_list(self, user_id: int = None):
        with Session(self.dbengine) as session:
            owners = [x.owner for x in session.exec(select(TgUser).where(TgUser.user_id == user_id)).all()]

            nfts = [
                NftListItem(address=x.address, name=x.name, species=x.species, species_name=x.species_name)
                for x in session.exec(
                    select(PetMemoryNft).where(PetMemoryNft.owner.in_(owners)).order_by(PetMemoryNft.id).limit(20)
                ).all()
            ]
            return owners, nfts

    async def nft_list(self, user_id: int = None):
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_nft_list, user_id)
        else:
            return self.sync_nft_list(user_id)

    def sync_nft_get(self, address: str = None):
        with Session(self.dbengine) as session:
            nft = session.exec(select(PetMemoryNft).where(PetMemoryNft.address == address)).one()
            session.expunge(nft)
            return nft, self.sync_get_collection(nft.collection_id)

    async def nft_get(self, address: str = None):
        if self.threadpool_executor:
            return await self.loop.run_in_executor(self.threadpool_executor, self.sync_nft_get, address)
        else:
            return self.sync_nft_get(address)
