import logging
from functools import partial

from sqlalchemy.exc import NoResultFound

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from aiogram.types import Message, CallbackQuery, User, WebAppInfo
from aiogram.filters.callback_data import CallbackData

from NFTorrent.modelsbase import TonAddress
from NFTorrent.translations import gettext

from ..main import _Bot
from ..services.nft import nft_preview
from ..states.nft import NftForm

logger = logging.getLogger(__name__)

router = Router()

def compress_address(addr: str, n: int=4) -> str:
    if len(addr) <= 2*n+3:
        return addr
    return f"{addr[:n]}...{addr[-n:]}"


class NftViewCallback(CallbackData, prefix="nftview"):
    address: str


@router.message(Command("nftlist"), F.chat.type == "private")
async def start(message: Message, command: CommandObject, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    bot: _Bot = message.bot
    owners, nfts = await bot.app.backend.nft_list(message.from_user.id)

    if not owners:
        builder = InlineKeyboardBuilder()
        builder.button(
            text=_("Connect wallet"),
            web_app=WebAppInfo(url=bot.app.get_petsmem_link(action="reconnect"))
        )

        await message.answer(
            _("To view your NFTs using this command, you must first authorize through the Mini App."),
           reply_markup=builder.as_markup()
        )
        return

    builder = InlineKeyboardBuilder()
    for nft in nfts:
        short_addr = compress_address(nft.address)
        label = f"{nft.name} {short_addr}"
        builder.button(
            text=label,
            callback_data=NftViewCallback(address=nft.address).pack()
        )
    builder.button(
        text=_("Mint"),
        web_app=WebAppInfo(url=bot.app.get_petsmem_link(action="mint"))
    )

    builder.adjust(2)
    await message.answer(
        _("Please select an NFT from the list to view details, or mint a new one.") if len(nfts) else _("You don't have any memorial NFTs yet. Consider minting your first one!")
        , reply_markup=builder.as_markup())


@router.message(Command("nftview"))
async def nft_view_command(message: Message, command: CommandObject, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)

    if not command.args:
        await message.answer(_("Send <b>NFT address</b> to view or /cancel"))
        await state.set_state(NftForm.address)
        return

    try:
        address = TonAddress(command.args.strip())
    except Exception:
        await message.answer(
            _("Provided input is not a valid TON Address. Please send the valid <b>NFT address</b> or just /cancel"),
        )
        await state.set_state(NftForm.address)
        return

    await _nvt_view(message.from_user, message, address.b64url)


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
            _("Provided input is not a valid TON Address. Please send the valid <b>NFT address</b> or just /cancel"),
        )
        return

    await state.clear()
    await _nvt_view(message.from_user, message, address.b64url)


@router.callback_query(NftViewCallback.filter())
async def nft_view_callback(callback: CallbackQuery, callback_data: NftViewCallback, state: FSMContext):
    _ = partial(gettext, callback.from_user.language_code)
    await _nvt_view(callback.from_user, callback.message, callback_data.address)
    await callback.answer()


async def _nvt_view(user: User, message: Message, address: str):
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
        await message.answer(
            text=_("Failed to view NFT <code>{address}</code>, error - {errorname}").format(address=address, errorname=type(E).__name__),
        )

