import datetime
import pickle
import logging
from functools import partial

from aiogram.types import BufferedInputFile, LinkPreviewOptions, InputMediaPhoto, User
from babel.dates import format_date

from NFTorrent.dbmodels import PetMemoryNft, PetsCollection, TgUser
from NFTorrent.translations import gettext
from NFTorrent.models import NftContentInfo

from ..keyboards.nft import main_nft_kb
from ..main import BotApp

logger = logging.getLogger(__name__)


def get_nft_icon(nft: PetMemoryNft):
    icons = pickle.loads(nft.icons)
    return BufferedInputFile(icons["medium"][0], filename=f"{nft.address}.webp")

async def notify_nft_minted(
    ch: BotApp, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False
):
    _ = partial(gettext, user.language)

    ipfslink = ch.get_ipfs_link(nft.image)
    storage_due_time = ""
    if ipfslink:
        storage_due_time = _("IPFS Storage due date: <b>{due_date}</b>\n").format(
            due_date=format_date(
                datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc),
                locale=user.language or "en",
            )
        )

    message = (
        _("✨ You have just minted memorial NFT\n\n")
        + _('<code>{nft_address}</code> - <a href="{tonviewer_link}">Tonviewer</a>\n\n{storage_due_time}')
    ).format(
        storage_due_time=storage_due_time,
        nft_address=nft.address,
        tonviewer_link=ch.get_tonviewer_link(nft.address),
    )

    await ch.bot.send_message(
        chat_id=user.user_id,
        text=message,
        parse_mode="HTML",
        reply_markup=main_nft_kb(ch, nft, collection, gettext=_) if keyboard else None,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def notify_nft_updated(
    ch: BotApp, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False
):
    _ = partial(gettext, user.language)

    ipfslink = ch.get_ipfs_link(nft.image)
    storage_due_time = ""
    if ipfslink:
        storage_due_time = _("IPFS Storage due date: <b>{due_date}</b>\n").format(
            due_date=format_date(
                datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc),
                locale=user.language or "en",
            )
        )

    message = (
        _("✨ You have just updated memorial NFT\n\n")
        + _('<code>{nft_address}</code> - <a href="{tonviewer_link}">Tonviewer</a>\n\n{storage_due_time}')
    ).format(
        storage_due_time=storage_due_time,
        nft_address=nft.address,
        tonviewer_link=ch.get_tonviewer_link(nft.address),
    )

    await ch.bot.send_message(
        chat_id=user.user_id,
        text=message,
        parse_mode="HTML",
        reply_markup=main_nft_kb(ch, nft, collection, gettext=_) if keyboard else None,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def nft_preview(app: BotApp, nft: PetMemoryNft, collection: PetsCollection, user: TgUser | User, keyboard: bool = False):
    if isinstance(user, TgUser):
        _ = partial(gettext, user.language)
        user_id = user.user_id
    else:
        _ = partial(gettext, user.language_code)
        user_id = user.id

    ipfslink = app.get_ipfs_link(nft.image)
    if ipfslink:
        ipfslink = f' • <a href="{ipfslink}">IPFS.io</a>'
    else:
        ipfslink = ""

    description = "\n".join([f"  {x}" for x in nft.description.split("\n")])
    message = (
        f"<b>{nft.name}</b> <i>({nft.birth_date} ~ {nft.death_date})</i>\n\n"
        f"{description}\n\n"
        f'<a href="{app.get_bot_miniapp_link(nft.address)}">Mini App</a>'
        f' • <a href="{app.get_petsmem_link(nft.address)}">Web App</a>'
        f' • <a href="{app.get_getgems_link(collection.address, nft.address)}">Getgems</a>'
        f' • <a href="{app.get_tonviewer_link(nft.address)}">Tonviewer</a>'
        f"{ipfslink}\n"
    )
    torrent_info = None
    media_urls = []
    if nft.torrent_info is not None:
        torrent_info: NftContentInfo = pickle.loads(nft.torrent_info)
        if torrent_info.files:
            media_urls = [
                app.get_petsmem_content_link(nft.address, digest=file.digest)
                for file in torrent_info.files
                if not file.name.startswith('.') and file.size <= app.torrent_file_size_limit
            ]
        else:
            media_urls = [app.get_petsmem_content_link(nft.address, digest=torrent_info.digest)]
    elif nft.image or nft.image_data:
        media_urls = [app.get_petsmem_content_link(nft.address)]

    try:
        if len(media_urls) > 1:
            await app.bot.send_media_group(
                chat_id=user_id,
                media=[
                    InputMediaPhoto(media=media, caption=message, parse_mode="HTML") if i == 0 else InputMediaPhoto(media=media)
                    for i, media in enumerate(media_urls)
                ]
            )
        elif len(media_urls) == 1:
            await app.bot.send_photo(
                chat_id=user_id,
                photo=media_urls[0],
                caption=message,
                parse_mode="HTML",
                reply_markup=main_nft_kb(app, nft, collection, gettext=_) if keyboard else None,
            )
        else:
            await app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="HTML",
                reply_markup=main_nft_kb(app, nft, collection, gettext=_) if keyboard else None,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    except Exception as E:
        logger.warning(
            "NFT preview error, address: %s, user_id: %s, username: %s - %s: %s",
            nft.address,
            user.id,
            user.username,
            type(E).__name__,
            E,
        )
        raise


async def notify_nft_storage_warning(
    app: BotApp, nft: PetMemoryNft, collection: PetsCollection, user: TgUser, keyboard: bool = False
):
    _ = partial(gettext, user.language)

    ipfslink = app.get_ipfs_link(nft.image)
    if not ipfslink:
        return

    fee_due_time = datetime.datetime.fromtimestamp(nft.fee_due_time, tz=datetime.timezone.utc)
    message = _(
        "⚠️ The guaranteed storage period for your NFT IPFS content ends on <b>{due_date}</b>.\n\n"
        "To keep your files available, consider extending it. Without renewal, availability after <b>{due_date}</b> cannot be guaranteed.\n\n"
        "We offers this service in exchange for a donation — your support helps keep service and your files online.\n"
    ).format(due_date=format_date(fee_due_time, locale=user.language or "en"))

    await app.bot.send_photo(
        chat_id=user.user_id,
        photo=get_nft_icon(nft),
        caption=message,
        parse_mode="HTML",
        reply_markup=(main_nft_kb(app, nft, collection, donate_btn=True, gettext=_) if keyboard else None),
    )
