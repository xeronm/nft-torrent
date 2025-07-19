import logging
from functools import partial

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.exc import NoResultFound

from NFTorrent.modelsbase import TonAddress
from NFTorrent.translations import gettext

from ..main import _Bot
from ..services.nft import nft_preview
from ..states.nft import NftForm

logger = logging.getLogger(__name__)

router = Router()

NFT_LIST_PAGE_SIZE = 20


def compress_address(addr: str, n: int = 4) -> str:
    if len(addr) <= 2 * n + 3:
        return addr
    return f"{addr[:n]}...{addr[-n:]}"


class NftViewCallback(CallbackData, prefix="nftview"):
    address: str


class NftListCallback(CallbackData, prefix="nftlist"):
    offset: int | None = 0


async def _nft_list(user: User, message: Message, offset: int = 0, edit: bool = False):
    _ = partial(gettext, user.language_code)
    offset = max(offset, 0)

    bot: _Bot = message.bot
    owners, nfts = await bot.app.backend.nft_list(user.id, offset=offset, limit=NFT_LIST_PAGE_SIZE)
    next_page = None
    if len(nfts) == NFT_LIST_PAGE_SIZE:
        # lookup next page
        try:
            __, next_page = await bot.app.backend.nft_list(
                user.id, offset=offset + NFT_LIST_PAGE_SIZE, limit=NFT_LIST_PAGE_SIZE
            )
        except Exception:
            pass
        # remove items to align keybard size
        if offset and len(nfts) == NFT_LIST_PAGE_SIZE:
            nfts.pop()
        if next_page:
            nfts.pop()

    if not owners:
        builder = InlineKeyboardBuilder()
        builder.button(text=_("Connect wallet"), web_app=WebAppInfo(url=bot.app.get_petsmem_link(action="reconnect")))

        await message.answer(
            _("To view your NFTs using this command, you must first authorize through the Mini App."),
            reply_markup=builder.as_markup(),
        )
        return

    builder = InlineKeyboardBuilder()
    if offset:
        prev_offset = offset - NFT_LIST_PAGE_SIZE + 1
        if prev_offset == 1:
            prev_offset = 0
        builder.button(text=_("◀️ Prev"), callback_data=NftListCallback(offset=prev_offset).pack())
    for nft in nfts:
        short_addr = compress_address(nft.address)
        label = f"{nft.name} {short_addr}"
        builder.button(text=label, callback_data=NftViewCallback(address=nft.address).pack())
    if next_page:
        builder.button(text=_("Next ▶️"), callback_data=NftListCallback(offset=offset + len(nfts)).pack())
    builder.button(text=_("✨ Mint"), web_app=WebAppInfo(url=bot.app.get_petsmem_link(action="mint")))

    builder.adjust(2)
    text = _(
        "Please select an NFT from the list to <b>view</b> details, or <b>mint</b> a new one.\n\nList of NFTs from {from_index} to {to_index}:"
    ).format(from_index=offset + 1, to_index=offset + len(nfts))
    if edit:
        await message.edit_text(
            (
                text
                if len(nfts)
                else _("You don’t have any NFTs starting from position {from_index}").format(from_index=offset + 1)
            ),
            reply_markup=builder.as_markup(),
        )
    else:
        await message.answer(
            (text if len(nfts) else _("You don't have any memorial NFTs yet. Consider minting your first one!")),
            reply_markup=builder.as_markup(),
        )


@router.message(Command("nftlist"), F.chat.type == "private")
async def nft_list(message: Message, command: CommandObject, state: FSMContext):
    await _nft_list(message.from_user, message, 0)


@router.callback_query(NftListCallback.filter())
async def nft_list_callback(callback: CallbackQuery, callback_data: NftListCallback, state: FSMContext):
    await _nft_list(callback.from_user, callback.message, offset=callback_data.offset, edit=True)


@router.message(Command("nftview"))
async def nft_view_command(message: Message, command: CommandObject, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)

    if not command.args:
        await message.answer(_("Send <b>NFT address</b> to view or /cancel."))
        await state.set_state(NftForm.address)
        return

    try:
        address = TonAddress(command.args.strip())
    except Exception:
        await message.answer(
            _("Provided input is not a valid TON Address. Please send the valid <b>NFT address</b> or just /cancel."),
        )
        await state.set_state(NftForm.address)
        return

    await _nft_view(message.from_user, message, address.b64url)


@router.message(NftForm.address, Command("cancel"))
async def cancel_address(message: Message, state: FSMContext):
    await state.clear()


@router.message(NftForm.address)
async def get_address(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    try:
        address = TonAddress(message.text.strip())
    except Exception:
        await message.answer(
            _(
                "The input you provided is not a valid TON address. Please send a valid <b>NFT address</b>, or just /cancel."
            ),
        )
        return

    await state.clear()
    await _nft_view(message.from_user, message, address.b64url)


@router.callback_query(NftViewCallback.filter())
async def nft_view_callback(callback: CallbackQuery, callback_data: NftViewCallback, state: FSMContext):
    await _nft_view(callback.from_user, callback.message, callback_data.address)
    await callback.answer()


async def _nft_view(user: User, message: Message, address: str):
    _ = partial(gettext, user.language_code)
    bot: _Bot = message.bot
    try:
        nft, collection = await bot.app.backend.nft_get(address)
        await nft_preview(bot.app, nft, collection, user)
    except NoResultFound:
        await message.answer(
            text=_("NFT <code>{address}</code> not found or not indexed yet.").format(address=address),
        )
    except Exception as E:
        logger.warning(
            "Failed to view NFT, user_id: %s, username: %s - %s: %s",
            user.id,
            user.username,
            type(E).__name__,
            E,
        )
        await message.answer(
            text=_("Failed to view NFT <code>{address}</code>, error - {errorname}").format(
                address=address, errorname=type(E).__name__
            ),
        )
