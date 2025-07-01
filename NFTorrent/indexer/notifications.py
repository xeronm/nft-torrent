import datetime
import logging
import pickle
from urllib.parse import urlencode, urljoin

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, WebAppInfo
from babel.dates import format_date

from NFTorrent.dbmodels import PetMemoryNft, PetsCollection, TgUser
from NFTorrent.translations import gettext_fn
from NFTorrent.utils import parse_ipfs_uri

logger = logging.getLogger(__name__)


class BotChannel:

    def __init__(
        self,
        token: str,
        getgems_authority: str = "https://testnet.getgems.io",
        ipfs_authority: str = "https://ipfs.io",
        petsmem_authority: str = "https://petsmem.site",
        tonviewer_authority: str = "https://testnet.tonviewer.com",
    ):
        self.bot = Bot(token)
        self.getgems_authority = getgems_authority
        self.ipfs_authority = ipfs_authority
        self.petsmem_authority = petsmem_authority
        self.tonviewer_authority = tonviewer_authority

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

    def get_tonviewer_link(self, nft_address: str):
        return urljoin(self.tonviewer_authority, f"/{nft_address}")

    def get_nft_keyboard(self, nft: PetMemoryNft, collection: PetsCollection, before_slot: list = None, gettext=None):
        _ = gettext or (lambda x: x)

        gglink = self.get_getgems_link(collection.address, nft.address)
        ipfslink = self.get_ipfs_link(nft.image)

        keyboard_row = [
            InlineKeyboardButton(text=_("View"), web_app=WebAppInfo(url=self.get_petsmem_link(nft.address))),
            InlineKeyboardButton(text=_("Getgems"), url=gglink),
        ]

        if ipfslink:
            keyboard_row += (InlineKeyboardButton(text=_("IPFS"), url=ipfslink),)
        keyboard = [keyboard_row]
        if before_slot:
            keyboard = [before_slot] + keyboard
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def get_nft_icon(self, nft: PetMemoryNft):
        icons = pickle.loads(nft.icons)
        return BufferedInputFile(icons["medium"][0], filename=f"{nft.address}.webp")

    async def send_ntf_minted(
        self, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False
    ):
        _ = gettext_fn(user.language)

        ipfslink = self.get_ipfs_link(nft.image)
        storage_due_time = ""
        if ipfslink:
            storage_due_time = _("IPFS Storage due date: <b>{due_date}</b>\n").format(
                due_date=format_date(
                    datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc),
                    locale=user.language or "en",
                )
            )

        message = (
            _("🕊️ You have just minted memorial NFT\n\n") +
            _('<code>{nft_address}</code> - <a href="{tonviewer_link}">view on Tonviewer</a>\n\n{storage_due_time}')
        ).format(
            storage_due_time=storage_due_time,
            nft_address=nft.address,
            tonviewer_link=self.get_tonviewer_link(nft.address),
        )

        await self.bot.send_message(
            chat_id=user.user_id,
            text=message,
            parse_mode="HTML",
            reply_markup=self.get_nft_keyboard(nft, collection, gettext=_) if keyboard else None,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def send_ntf_updated(
        self, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False
    ):
        _ = gettext_fn(user.language)

        ipfslink = self.get_ipfs_link(nft.image)
        storage_due_time = ""
        if ipfslink:
            storage_due_time = _("IPFS Storage due date: <b>{due_date}</b>\n").format(
                due_date=format_date(
                    datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc),
                    locale=user.language or "en",
                )
            )

        message = (
            _("🕊️ You have just updated memorial NFT\n\n") +
            _('<code>{nft_address}</code> - <a href="{tonviewer_link}">view on Tonviewer</a>\n\n{storage_due_time}')
        ).format(
            storage_due_time=storage_due_time,
            nft_address=nft.address,
            tonviewer_link=self.get_tonviewer_link(nft.address),
        )

        await self.bot.send_message(
            chat_id=user.user_id,
            text=message,
            parse_mode="HTML",
            reply_markup=self.get_nft_keyboard(nft, collection, gettext=_) if keyboard else None,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def send_ntf_preview(
        self, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False
    ):
        _ = gettext_fn(user.language)

        ipfslink = self.get_ipfs_link(nft.image)
        if ipfslink:
            ipfslink = f' • <a href="{ipfslink}">IPFS Gateway</a>'
        else:
            ipfslink = ""

        description = "\n".join([f"  {x}" for x in nft.description.split("\n")])
        message = (
            f"<b>{nft.name}</b> <i>({nft.birth_date} ~ {nft.death_date})</i>\n\n"
            f"{description}\n\n"
            f'<a href="{self.get_petsmem_link(nft.address)}">Pets Memorial</a>'
            f' • <a href="{self.get_getgems_link(collection.address, nft.address)}">Getgems</a>'
            f"{ipfslink}\n"
        )
        if nft.icons:
            await self.bot.send_photo(
                chat_id=user.user_id,
                photo=self.get_nft_icon(nft),
                caption=message,
                parse_mode="HTML",
                reply_markup=self.get_nft_keyboard(nft, collection, gettext=_) if keyboard else None,
            )
        else:
            await self.bot.send_message(
                chat_id=user.user_id,
                text=message,
                parse_mode="HTML",
                reply_markup=self.get_nft_keyboard(nft, collection, gettext=_) if keyboard else None,
            )

    async def send_nft_storage_warning(
        self, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False
    ):
        _ = gettext_fn(user.language)

        ipfslink = self.get_ipfs_link(nft.image)
        if not ipfslink:
            return

        fee_due_time = datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc)
        message = _(
            "⚠️ The guaranteed storage period for your NFT IPFS content ends on <b>{due_date}</b>.\n\n"
            "To keep your files available, consider extending it. Without renewal, availability after <b>{due_date}</b> cannot be guaranteed.\n\n"
            "We offers this service in exchange for a donation — your support helps keep service and your files online.\n"
        ).format(due_date=format_date(fee_due_time, locale=user.language or "en"))

        before_slot = [
            InlineKeyboardButton(
                text=_("Donate (Renew storage)"),
                web_app=WebAppInfo(url=self.get_petsmem_link(nft.address, {"doante": 1})),
            ),
        ]

        await self.bot.send_photo(
            chat_id=user.user_id,
            photo=self.get_nft_icon(nft),
            caption=message,
            parse_mode="HTML",
            reply_markup=(
                self.get_nft_keyboard(nft, collection, before_slot=before_slot, gettext=_) if keyboard else None
            ),
        )
