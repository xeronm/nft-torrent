import asyncio
import datetime
import os

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlmodel import Session, SQLModel, create_engine, delete, select, update

from NFTorrent.bot import BackendInterface, BaseInquiry, BotApp
from NFTorrent.bot.handlers import inquiry
from NFTorrent.dbmodels import UserInquiry, UserInquiryState

token = os.environ["CI_BOT_TOKEN"]
dbpassword = os.environ["CI_DATABASE_PASSWORD"]


class Backend(BackendInterface):

    def __init__(self, url: str):
        self.dbengine = create_engine(url)
        SQLModel.metadata.create_all(self.dbengine)

    async def inquiry_list(self, user) -> list[BaseInquiry]:
        with Session(self.dbengine) as session:
            items = [
                BaseInquiry(**x.model_dump())
                for x in session.exec(
                    select(UserInquiry).where((UserInquiry.user_id == user.id) & (UserInquiry.state.is_not(None)))
                ).all()
            ]
        return items

    async def inquiry_create(self, user, data) -> BaseInquiry:
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

    async def inquiry_close(
        self, inquiry_id: str, user_id: int = None, admin_user_id: int = None, admin_message: str = None
    ) -> BaseInquiry:
        with Session(self.dbengine) as session:
            inquiry = session.exec(select(UserInquiry).where(UserInquiry.inquiry_id == inquiry_id).with_for_update()).one()

            if user_id is not None and inquiry.user_id != user_id:
                raise RuntimeError("Forbiden")
            if inquiry.state is None:
                raise RuntimeError("Closed")

            curr_time = datetime.datetime.now(datetime.timezone.utc)
            inquiry.admin_user_id = admin_user_id if admin_user_id is not None else user_id
            inquiry.admin_message = admin_message
            inquiry.updated_time = curr_time
            inquiry.closed_time = curr_time
            inquiry.state = None
            base_inquiry = BaseInquiry(**inquiry.model_dump())
            session.commit()
            return base_inquiry

    async def inquiry_block(
        self, inquiry_id: str, admin_user_id: int = None, admin_message: str = None, disable_to_hours: int = None
    ) -> BaseInquiry:
        with Session(self.dbengine) as session:
            inquiry = session.exec(
                select(UserInquiry).where(UserInquiry.inquiry_id == inquiry_id).with_for_update()
            ).one()
            if inquiry.state is None:
                raise RuntimeError("Closed")
            curr_time = datetime.datetime.now(datetime.timezone.utc)
            inquiry.admin_user_id = admin_user_id
            inquiry.admin_message = admin_message
            inquiry.updated_time = curr_time
            inquiry.disabled_to = curr_time + datetime.timedelta(hours=disable_to_hours)
            base_inquiry = BaseInquiry(**inquiry.model_dump())
            session.commit()
            return base_inquiry

    async def inquiry_get(self, inquiry_id: str) -> BaseInquiry:
        with Session(self.dbengine) as session:
            inquiry = session.exec(select(UserInquiry).where(UserInquiry.inquiry_id == inquiry_id)).one()

            return BaseInquiry(**inquiry.model_dump())


def main():

    bot = BotApp(
        token,
        admin_group_id=-1002890915463,
        backend=Backend(f"postgresql+psycopg2://postgres:{dbpassword}@172.16.1.1:6432/postgres"),
    )

    async def __poll():
        dp = Dispatcher(storage=MemoryStorage())

        dp.include_routers(
            inquiry.router,
        )

        await dp.start_polling(bot.bot)

    print("Starting test Bot...")
    asyncio.run(__poll())


main()
