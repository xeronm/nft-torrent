import logging
from functools import partial

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User
from aiogram.utils.keyboard import InlineKeyboardBuilder
from babel.dates import format_datetime

from NFTorrent.translations import gettext

from ..keyboards.inquiry import inquiry_admin_kb
from ..main import _Bot
from .utils import is_admin_callback, is_admin_command

logger = logging.getLogger(__name__)


INQUIRY_LIST_PAGE_SIZE = 20


router = Router()


@router.message(Command("stats"))
async def stats(message: Message, command: CommandObject, state: FSMContext):
    if not is_admin_command(message, command):
        return
    bot: _Bot = message.bot
    await message.answer(
        text=("Bot statistics: <pre>{bot_stats}</pre>\n\n" "DB statistics: <pre>{db_stats}</pre>").format(
            bot_stats="\n".join(bot.app.stats.as_influx()),
            db_stats=await bot.app.backend.dbstats(),
        ),
        disable_notification=True,
    )


class InquiryListCallback(CallbackData, prefix="inqlist"):
    offset: int | None = 0


class InquiryViewCallback(CallbackData, prefix="inqview"):
    inquiry_id: str


async def _inquiry_list(user: User, message: Message, offset: int = 0, edit: bool = False):
    _ = partial(gettext, user.language_code)
    offset = max(offset, 0)

    bot: _Bot = message.bot
    inquiries = await bot.app.backend.inquiry_list(offset=offset, limit=INQUIRY_LIST_PAGE_SIZE)
    next_page = None
    if len(inquiries) == INQUIRY_LIST_PAGE_SIZE:
        # lookup next page
        try:
            next_page = await bot.app.backend.nft_list(
                offset=offset + INQUIRY_LIST_PAGE_SIZE, limit=INQUIRY_LIST_PAGE_SIZE
            )
        except Exception:
            pass
        # remove items to align keybard size
        if offset and len(inquiries) == INQUIRY_LIST_PAGE_SIZE:
            inquiries.pop()
        if next_page:
            inquiries.pop()

    builder = InlineKeyboardBuilder()
    if offset:
        prev_offset = offset - INQUIRY_LIST_PAGE_SIZE + 1
        if prev_offset == 1:
            prev_offset = 0
        builder.button(text=_("◀️ Prev"), callback_data=InquiryListCallback(offset=prev_offset).pack())
    for inq in inquiries:
        label = f"#R{inq.id:06d} {inq.username:.20}"
        builder.button(text=label, callback_data=InquiryViewCallback(inquiry_id=inq.inquiry_id).pack())
    if next_page:
        builder.button(text=_("Next ▶️"), callback_data=InquiryListCallback(offset=offset + len(inquiries)).pack())

    builder.adjust(2)
    text = _(
        "Please select an Inquiry from the list to <b>view</b> details.\n\nList of Inquiries from {from_index} to {to_index}:"
    ).format(from_index=offset + 1, to_index=offset + len(inquiries))
    if edit:
        await message.edit_text(
            text if len(inquiries) else _("There are no opened inquiries starting from position {from_index}").format(from_index=offset + 1),
            reply_markup=builder.as_markup(),
        )
    else:
        await message.answer(
            (text if len(inquiries) else _("There are no opened inquiries!")),
            reply_markup=builder.as_markup(),
        )


@router.message(Command("inqlist"))
async def inquiry_list(message: Message, command: CommandObject, state: FSMContext):
    if not is_admin_command(message, command):
        return
    await _inquiry_list(message.from_user, message, 0)


@router.callback_query(InquiryListCallback.filter())
async def inquiry_list_callback(callback: CallbackQuery, callback_data: InquiryListCallback, state: FSMContext):
    if not is_admin_callback(callback, callback_data):
        return
    await _inquiry_list(callback.from_user, callback.message, offset=callback_data.offset, edit=True)


async def _inquiry_view(user: User, message: Message, inquiry_id: str):
    _ = partial(gettext, user.language_code)
    bot: _Bot = message.bot
    try:
        inquiry = await bot.app.backend.inquiry_get(inquiry_id=inquiry_id)
    except Exception as E:
        logger.warning(
            "Inquiry get error, user_id: %s, username: %s - %s: %s",
            user.id,
            user.username,
            type(E).__name__,
            E,
        )
        await message.answer(
            _("Failed to get Inquiry: {errorname}").format(errorname=type(E).__name__),
        )
        return

    await message.answer(
        _(
            "Inquiry: #R{inquiry_num:06d} from @{username}\n\nCreated: {created}\nUpdated: {updated}\nDisabled to: {block_date}\nClosed: {closed}"
        ).format(
            inquiry_num=inquiry.id,
            username=inquiry.username,
            created=format_datetime(inquiry.created_time, locale=user.language_code),
            updated=format_datetime(inquiry.updated_time, locale=user.language_code),
            closed=format_datetime(inquiry.closed_time, locale=user.language_code) if inquiry.closed_time else "-",
            block_date=(
                format_datetime(
                    inquiry.disabled_to,
                    locale=user.language_code,
                )
                if inquiry.disabled_to
                else "-"
            ),
        ),
        disable_notification=True,
        reply_markup=(
            inquiry_admin_kb(inquiry_id=inquiry_id, message_id=inquiry.message_id, user_id=inquiry.user_id, gettext=_)
            if inquiry.closed_time is None
            else None
        ),
    )


@router.callback_query(InquiryViewCallback.filter())
async def inquiry_view_callback(callback: CallbackQuery, callback_data: InquiryViewCallback, state: FSMContext):
    if not is_admin_callback(callback, callback_data):
        return
    await _inquiry_view(callback.from_user, callback.message, callback_data.inquiry_id)
    await callback.answer()
