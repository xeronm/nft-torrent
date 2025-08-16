import copy
import datetime
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ReplyMarkupUnion, User
from pydantic import BaseModel

from NFTorrent.dbmodels import PetMemoryNft, PetsCollection
from NFTorrent.modelsbase import (
    MeasurementStore,
    StatisticMeasurement,
)
from NFTorrent.utils import parse_ipfs_uri, uri_ipfs

logger = logging.getLogger(__name__)


MAX_CAPTION_LENGTH = 1500


class NftListItem(BaseModel):
    address: str
    name: str
    species: int
    species_name: str | None


class BaseInquiry(BaseModel):
    id: int
    inquiry_id: str
    state: int | None
    user_id: int
    username: str
    disabled_to: datetime.datetime | None


class BackendError(Exception):
    pass


class BackendForbidden(BackendError):
    pass


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
    async def inquiry_list(self, user_id: int = None) -> list[BaseInquiry]:
        pass

    @abstractmethod
    async def inquiry_get(self, inquiry_id: str) -> BaseInquiry:
        pass

    @abstractmethod
    async def nft_list(
        self, user_id: int = None, offset: int = 0, limit: int = 20
    ) -> tuple[list[str], list[NftListItem]]:
        pass

    @abstractmethod
    async def nft_get(self, address: str = None) -> tuple[PetMemoryNft, PetsCollection]:
        pass


class BotApp:

    def __init__(
        self,
        token: str,
        getgems_authority: str = "https://testnet.getgems.io",
        ipfs_authority: str = "https://ipfs.io",
        petsmem_authority: str = "https://petsmem.site",
        petsmem_content_authority: str = "https://w.petsmem.site",
        tonviewer_authority: str = "https://testnet.tonviewer.com",
        bot_miniapp_authority: str = "https://t.me/pets_memorial_bot/petsmem",
        admin_group_id: int = None,
        backend: BackendInterface = None,
        torrent_file_size_limit=None,
        node_id: str = "undefined",
    ):
        self.bot_id = token.split(":")[0]
        self.bot = _Bot(token=token, app=self, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.getgems_authority = getgems_authority
        self.ipfs_authority = ipfs_authority
        self.petsmem_authority = petsmem_authority
        self.petsmem_content_authority = petsmem_content_authority
        self.tonviewer_authority = tonviewer_authority
        self.bot_miniapp_authority = bot_miniapp_authority
        self.admin_group_id = admin_group_id
        self.backend = backend
        self.torrent_file_size_limit = torrent_file_size_limit
        self.stats = MeasurementStore("NFTorrentBotApp", StatisticMeasurement)
        self.node_id = node_id

    def get_getgems_link(self, collection: str, nft_address: str) -> str:
        return urljoin(self.getgems_authority, f"/collection/{collection}/{nft_address}")

    def get_ipfs_link(self, url: str) -> str:
        if not uri_ipfs(url):
            return None
        cid, _, _ = parse_ipfs_uri(url)
        return urljoin(self.ipfs_authority, f"/ipfs/{cid}")

    def get_petsmem_content_link(self, nft_address: str, digest: str = None):
        url = urljoin(self.petsmem_content_authority, f"/c/{nft_address}")
        if digest:
            url = urljoin(url + "/", digest)
        return url

    def get_petsmem_link(self, nft_address: str = None, action: str = None, query_params: dict = None):
        url = self.petsmem_authority
        if nft_address:
            url = urljoin(url, f"/nft/{nft_address}")
        if query_params or action:
            query_params = copy.deepcopy(query_params) or {}
            if action:
                query_params["action"] = action
            url = f"{url}?{urlencode(query_params)}"
        return url

    def get_bot_miniapp_link(self, nft_address: str = None, action: str = None, query_params: dict = None):
        query_params = copy.deepcopy(query_params) or {}
        if nft_address:
            query_params["nft"] = nft_address
        if action:
            query_params["action"] = action
        outer_query = {"startapp": urlencode(query_params)}
        url = f"{self.bot_miniapp_authority}?{urlencode(outer_query)}"
        return url

    def get_tonviewer_link(self, nft_address: str):
        return urljoin(self.tonviewer_authority, f"/{nft_address}")

    def get_bot_state(self):
        return self.stats.as_list() + self.backend.stats.as_list() + self.backend.stats_db.as_list()

    def get_measurements(self, timestamp: int) -> list[str]:
        return (
            self.stats.as_influx(timestamp)
            + self.backend.stats.as_influx(timestamp)
            + self.backend.stats_db.as_influx(timestamp)
        )


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


__all__ = ["BotApp", "BackendInterface", "BaseInquiry", "MAX_CAPTION_LENGTH"]
