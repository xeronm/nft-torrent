import pickle
import datetime
from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from NFTorrent.dbmodels import TgUser, PetsCollection, PetMemoryNft
from NFTorrent.utils import parse_ipfs_uri
from urllib.parse import urlencode, urljoin
from babel.dates import format_datetime
from NFTorrent.translations import gettext_fn



class BotChannel:

    def __init__(self, token: str, getgems_authority: str = 'https://testnet.getgems.io', ipfs_authority: str = 'https://ipfs.io', petsmem_authority='https://petsmem.site'):
        self.bot = Bot(token)
        self.getgems_authority = getgems_authority
        self.ipfs_authority = ipfs_authority
        self.petsmem_authority = petsmem_authority

    def get_getgems_link(self, collection: str, nft_address: str) -> str:
        return urljoin(self.getgems_authority, f"/collection/{collection}/{nft_address}")

    def get_ipfs_link(self, url: str) -> str:
        if not url.startswith("ipfs://"):
            return None
        cid, _, _ = parse_ipfs_uri(url)
        return urljoin(self.ipfs_authority, f"/ipfs/{cid}")

    def get_petsmem_link(self, nft_address: str, query_params: dict = None):
        url = urljoin(self.petsmem_authority, f"/#/nft/{nft_address}")
        if query_params:
            url = f"{url}?{urlencode(query_params)}"
        return url

    def get_nft_keyboard(self, nft: PetMemoryNft, collection: PetsCollection, before_slot: list = None, gettext = None):
        _ = gettext or (lambda x: x)

        gglink = self.get_getgems_link(collection.address, nft.address)
        ipfslink = self.get_ipfs_link(nft.image)

        keyboard_row = [
            InlineKeyboardButton(text=_("View"), web_app=WebAppInfo(url=self.get_petsmem_link(nft.address))),
            InlineKeyboardButton(text=_("Getgems"), url=gglink),
        ]

        if ipfslink:
            keyboard_row += InlineKeyboardButton(text=_("IPFS"), url=ipfslink),
        return InlineKeyboardMarkup(inline_keyboard=([before_slot] or []) + [keyboard_row])

    def get_nft_icon(self, nft: PetMemoryNft):
        icons = pickle.loads(nft.icons)
        return BufferedInputFile(icons["medium"][0], filename=f"{nft.address}.webp")

    async def send_ntf_mint(self, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False):
        _ = gettext_fn(user.language)

        ipfslink = self.get_ipfs_link(nft.image)
        if ipfslink:
            fee_due_time = datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc)

        message = _(
            "🕊️ You have just minted memorial NFT\n\n"
            "Storage due date: {due_date}"
        ).format(due_date=format_datetime(fee_due_time, locale=user.language or 'en'))

        await self.bot.send_message(
            chat_id=user.user_id,
            text=message,
            parse_mode="HTML",
            reply_markup=self.get_nft_keyboard(nft, collection, gettext=_) if keyboard else None)

    async def send_ntf_preview(self, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False):
        _ = gettext_fn(user.language)

        ipfslink = self.get_ipfs_link(nft.image)
        if ipfslink:
            ipfslink = f' • <a href="{ipfslink}">IPFS Gateway</a>'

        description = '\n'.join([f'  {x}' for x in nft.description.split('\n')])
        message = (
            f"<b>{nft.name}</b> <i>({nft.birth_date} ~ {nft.death_date})</i>\n\n"
            f"{description}\n\n"
            f'<a href="{self.get_petsmem_link(nft.address)}">Pets Memorial</a>'
            f' • <a href="{self.get_getgems_link(collection.address, nft.address)}">Getgems</a>'
            f'{ipfslink}\n'

        )
        await self.bot.send_photo(
            chat_id=user.user_id,
            photo=self.get_nft_icon(nft),
            caption=message,
            parse_mode="HTML",
            reply_markup=self.get_nft_keyboard(nft, collection, gettext=_) if keyboard else None
        )

    async def send_nft_storage_warning(self, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False):
        _ = gettext_fn(user.language)

        ipfslink = self.get_ipfs_link(nft.image)
        if not ipfslink:
            return

        fee_due_time = datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc)
        message = _(
            "⚠️ The guaranteed storage period for your NFT IPFS content ends on <b>{due_date}</b>.\n\n"
            "To keep your files available, consider extending it. Without renewal, availability after <b>{due_date}</b> cannot be guaranteed.\n\n"
            "We offers this service in exchange for a donation — your support helps keep service and your files online.\n"
        ).format(due_date=format_datetime(fee_due_time, locale=user.language or 'en'))

        before_slot = [
            InlineKeyboardButton(text=_("Donate (Renew storage)"), web_app=WebAppInfo(url=self.get_petsmem_link(nft.address, {'doante': 1}))),
        ]

        await self.bot.send_photo(
            chat_id=user.user_id,
            photo=self.get_nft_icon(nft),
            caption=message,
            parse_mode="HTML",
            reply_markup=self.get_nft_keyboard(nft, collection, before_slot=before_slot, gettext=_) if keyboard else None
        )