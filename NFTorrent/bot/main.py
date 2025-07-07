import base64
import logging
import secrets
import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict
from urllib.parse import urlencode, urljoin

from aiogram import BaseMiddleware, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyMarkupUnion, TelegramObject, User
from pydantic import BaseModel

from NFTorrent.utils import parse_ipfs_uri

logger = logging.getLogger(__name__)


class BaseInquiry(BaseModel):
    id: int
    inquiry_id: str
    state: int | None
    user_id: int
    username: str
    disabled_to: datetime.datetime | None


class BackendInterface(ABC):

    @abstractmethod
    async def inquiry_create(self, user: User, data: dict[Any, Any]) -> BaseInquiry:
        pass

    @abstractmethod
    async def inquiry_close(
        self, inquiry_id: str, user_id: int = None, admin_user_id: int = None, admin_message: str = None
    ) -> BaseInquiry:
        pass

    @abstractmethod
    async def inquiry_block(
        self, inquiry_id: str, admin_user_id: int = None, admin_message: str = None, disable_to_hours: int = None
    ) -> BaseInquiry:
        pass

    @abstractmethod
    async def inquiry_list(self, user: User) -> list[BaseInquiry]:
        pass

    @abstractmethod
    async def inquiry_get(self, inquiry_id: str) -> BaseInquiry:
        pass


class BotApp:

    def __init__(
        self,
        token: str,
        getgems_authority: str = "https://testnet.getgems.io",
        ipfs_authority: str = "https://ipfs.io",
        petsmem_authority: str = "https://petsmem.site",
        tonviewer_authority: str = "https://testnet.tonviewer.com",
        bot_miniapp_authority: str = "https://t.me/pets_memorial_bot/petsmem",
        admin_group_id: int = None,
        backend: BackendInterface = None,
    ):
        self.bot = _Bot(token=token, app=self, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.getgems_authority = getgems_authority
        self.ipfs_authority = ipfs_authority
        self.petsmem_authority = petsmem_authority
        self.tonviewer_authority = tonviewer_authority
        self.bot_miniapp_authority = bot_miniapp_authority
        self.admin_group_id = admin_group_id
        self.backend = backend

    def get_getgems_link(self, collection: str, nft_address: str) -> str:
        return urljoin(self.getgems_authority, f"/collection/{collection}/{nft_address}")

    def get_ipfs_link(self, url: str) -> str:
        if not url or not url.startswith("ipfs://"):
            return None
        cid, _, _ = parse_ipfs_uri(url)
        return urljoin(self.ipfs_authority, f"/ipfs/{cid}")

    def get_petsmem_link(self, nft_address: str, query_params: dict = None):
        url = urljoin(self.petsmem_authority, f"/#/nft/{nft_address}")
        if query_params:
            url = f"{url}?{urlencode(query_params)}"
        return url

    def get_bot_miniapp_link(self, nft_address: str, query_params: dict = None):
        query_params = query_params or {}
        query_params["nft"] = nft_address
        outer_query = {"startapp": urlencode(query_params)}
        url = f"{self.bot_miniapp_authority}?{urlencode(outer_query)}"
        return url

    def get_tonviewer_link(self, nft_address: str):
        return urljoin(self.tonviewer_authority, f"/{nft_address}")


class _Bot(Bot):
    def __init__(self, token: str, app: BotApp, **kwargs):
        super().__init__(token, **kwargs)
        self.app = app


@dataclass
class MessageDesc:
    key: str
    chat_id: int
    message_id: int
    reply_markup: ReplyMarkupUnion = None


def random_dialog_id():
    return base64.urlsafe_b64encode(secrets.token_bytes(15)).decode()


@dataclass
class MessageDialog:
    dialog_id: str = field(default_factory=random_dialog_id)
    changed: bool = False
    msgs: list[MessageDesc] = field(default_factory=list)

    def append(self, msg: MessageDesc):
        self.changed = True
        self.msgs.append(msg)

    async def delete_reply_markup(self, bot: Bot):
        for message in self.msgs:
            if message.reply_markup is None:
                continue
            try:
                await bot.edit_message_reply_markup(
                    chat_id=message.chat_id, message_id=message.message_id, reply_markup=None
                )
                message.reply_markup = None
            except Exception as E:
                logger.warning(
                    "MessageDialog delete reply markup error, chat_id: %s, msg_id: %s - %s: %s",
                    message.chat_id,
                    message.message_id,
                    type(E).__name__,
                    E,
                )


class DialogMiddleware(BaseMiddleware):

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        state: FSMContext = data["state"]
        state_data = await state.get_data()
        dialog: MessageDialog = state_data.get("_dialog", MessageDialog())
        data["dialog"] = dialog

        message = None
        if isinstance(event, Message):
            message = event
        if isinstance(event, CallbackQuery):
            message = event.message

        if message is not None:
            __answer = message.answer

            async def _answer(*args, message_key: str = None, **kwargs):
                msg: Message = await __answer(*args, **kwargs)

                dialog.append(
                    MessageDesc(
                        key=message_key, chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=msg.reply_markup
                    )
                )
                return msg

            object.__setattr__(message, "answer", _answer)
            object.__setattr__(message, "raw_answer", __answer)

        try:
            return await handler(event, data)
        finally:
            if dialog.changed:
                dialog.changed = False
                await state.update_data(_dialog=dialog)


__all__ = ["BotApp", "DialogMiddleware", "BackendInterface", "BaseInquiry"]
