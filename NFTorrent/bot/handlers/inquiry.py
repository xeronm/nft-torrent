import base64
import datetime
import logging
import secrets
from functools import partial

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message
from babel.dates import format_datetime

from NFTorrent.modelsbase import TonAddress
from NFTorrent.translations import gettext

from ..keyboards.inquiry import inquiry_admin_kb, inquiry_user_kb, new_inquiry_kb
from ..main import BaseInquiry, _Bot
from ..states.inquiry import InquiryAction, InquiryCallback, InquiryForm, InquiryReplyCallback, InquiryReplyForm

logger = logging.getLogger(__name__)

router = Router()


def random_inquiry_id():
    return base64.urlsafe_b64encode(secrets.token_bytes(15)).decode()


@router.message(Command("get_id"))
async def get_chat_id(message: Message):
    await message.answer(f"Chat ID: `{message.chat.id}`", parse_mode="Markdown")


@router.message(Command("start"), F.chat.type == "private")
async def start(message: Message, command: CommandObject, state: FSMContext):
    if command.args == "inquiry":
        await start_inquiry(message, state)


#
# Helpers
#
async def context_lost(callback: CallbackQuery):
    _ = partial(gettext, callback.from_user.language_code)
    await callback.bot.edit_message_reply_markup(
        chat_id=callback.message.chat.id, message_id=callback.message.message_id, reply_markup=None
    )
    await callback.message.answer(
        _("⚠️ Your Inquiry session has timed out. Please start a new one with /inquiry."),
    )
    await callback.answer()


async def callback_validate_inquiry(inquiry: BaseInquiry, callback: CallbackQuery, verify_blocked: bool = True):
    _ = partial(gettext, callback.from_user.language_code)
    if inquiry.state is None:
        await callback.bot.edit_message_reply_markup(
            chat_id=callback.message.chat.id, message_id=callback.message.message_id, reply_markup=None
        )
        # await callback.message.answer(
        #     _("⚠️ This inquiry has already been <b>closed</b> and cannot be updated."),
        # )
        await callback.answer(
            _("⚠️ This inquiry has already been <b>closed</b> and cannot be updated."), show_alert=False
        )
        return False

    curr_time = datetime.datetime.now(datetime.timezone.utc)
    if (
        verify_blocked
        and inquiry.disabled_to
        and inquiry.disabled_to.replace(tzinfo=datetime.timezone.utc) >= curr_time
    ):
        await callback.message.answer(
            _("🚫 User Inquiry #R{inquiry_num:06d} has been <b>blocked</b> up to {block_date} UTC.").format(
                inquiry_num=inquiry.id,
                block_date=format_datetime(
                    inquiry.disabled_to,
                    locale=callback.from_user.language_code,
                ),
            ),
        )
        await callback.answer()
        return False
    return True


#
# User InquiryReplyForm
#
@router.callback_query(InquiryReplyCallback.filter(F.user_id == 0))
async def user_reply_inquiry(callback: CallbackQuery, callback_data: InquiryReplyCallback, state: FSMContext):
    _ = partial(gettext, callback_data.lang)
    bot: _Bot = callback.bot
    try:
        inquiry = await bot.app.backend.inquiry_get(inquiry_id=callback_data.inquiry_id)
    except Exception as E:
        logger.warning(
            "Inquiry get error, user_id: %s, username: %s - %s: %s",
            callback.from_user.id,
            callback.from_user.username,
            type(E).__name__,
            E,
        )
        await callback.answer(
            text=_("Failed to get Inquiry: {errorname}").format(errorname=type(E).__name__),
            show_alert=False,
            cache_time=30,
        )
        return

    if inquiry.user_id != callback.from_user.id:
        logger.warning(
            "Unathorized command: %s, user_id: %s, username: %s",
            callback_data.pack(),
            callback.from_user.id,
            callback.from_user.username,
        )
        return

    if not await callback_validate_inquiry(inquiry, callback):
        return

    action_message = None
    if callback_data.action == InquiryAction.Reply.value:
        action_message = _("Reply message")
    elif callback_data.action == InquiryAction.Close.value:
        action_message = _("Close message")

    await state.clear()
    await state.set_state(InquiryReplyForm.user_reply)
    await state.update_data(
        reply_action=callback_data.action,
        inquiry_id=callback_data.inquiry_id,
        message_id=callback_data.message_id,
        callback_message_id=callback.message.message_id,
    )
    await callback.message.reply(
        _(
            "Type your <b>{action_message}</b> or /cancel.\n" "It will be added to your Inquiry #R{inquiry_num:06d}."
        ).format(
            inquiry_num=inquiry.id,
            action_message=action_message,
        ),
        # reply_markup=inquiry_reply_kb(gettext=_),
    )
    await callback.answer()


@router.message(InquiryReplyForm.user_reply, Command("cancel"))
async def user_cancel_reply(message: Message, state: FSMContext):
    await state.clear()


@router.message(InquiryReplyForm.user_reply)
async def user_get_reply(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)

    bot: _Bot = message.bot

    data = await state.get_data()
    reply_action = data["reply_action"]
    inquiry_id = data["inquiry_id"]
    message_id = data["message_id"]
    try:
        inquiry = None
        try:
            if reply_action == InquiryAction.Close.value:
                inquiry = await bot.app.backend.inquiry_close(inquiry_id=inquiry_id, user_id=message.from_user.id)
            elif reply_action == InquiryAction.Reply.value:
                inquiry = await bot.app.backend.inquiry_get(inquiry_id=inquiry_id)
        except Exception as E:
            logger.warning(
                "Inquiry update error, user_id: %s, username: %s - %s: %s",
                message.from_user.id,
                message.from_user.username,
                type(E).__name__,
                E,
            )
            await message.reply(
                _("Failed to update Inquiry: {errorname}").format(errorname=type(E).__name__),
            )
            return

        if reply_action == InquiryAction.Reply.value:
            # Send to admin channel
            await bot.send_message(
                bot.app.admin_group_id,
                _(
                    "📩 Inquiry #R{inquiry_num:06d} from user @{username} has received a <b>Reply</b> from the user with the following message\n"
                ).format(inquiry_num=inquiry.id, username=inquiry.username, message=message.text),
                reply_markup=inquiry_admin_kb(
                    inquiry_id=inquiry_id, message_id=message.message_id, user=message.from_user, gettext=_
                ),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )

            await message.reply(
                _("📩 You’ve sent a reply to your inquiry #R{inquiry_num:06d}.").format(inquiry_num=inquiry.id)
            )
        elif reply_action == InquiryAction.Close.value:
            # Send to admin channel
            await bot.send_message(
                bot.app.admin_group_id,
                _(
                    "✅ Inquiry #R{inquiry_num:06d} from user @{username} has been <b>Closed</b> by user with the following message\n\n{message}"
                ).format(inquiry_num=inquiry.id, username=inquiry.username, message=message.text),
                reply_to_message_id=message_id if message_id else None,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            await message.reply(
                _("✅ Your Inquiry #R{inquiry_num:06d} has been closed.").format(inquiry_num=inquiry.id)
            )
    except Exception as e:
        await message.reply(f"Failed to send reply: {e}")
    await state.clear()


#
# Admin InquiryReplyForm
#
@router.callback_query(InquiryReplyCallback.filter(F.user_id != 0))
async def admin_reply_inquiry(callback: CallbackQuery, callback_data: InquiryReplyCallback, state: FSMContext):
    if callback.message.chat.id != callback.bot.app.admin_group_id:
        logger.warning(
            "Unathorized command: %s, user_id: %s, username: %s",
            callback_data.pack(),
            callback.from_user.id,
            callback.from_user.username,
        )
        return

    _ = partial(gettext, callback_data.lang)

    bot: _Bot = callback.bot
    try:
        inquiry = await bot.app.backend.inquiry_get(inquiry_id=callback_data.inquiry_id)
    except Exception as E:
        logger.warning(
            "Inquiry get error, user_id: %s, username: %s - %s: %s",
            callback.from_user.id,
            callback.from_user.username,
            type(E).__name__,
            E,
        )
        await callback.message.answer(
            _("Failed to get Inquiry: {errorname}").format(errorname=type(E).__name__),
        )
        return

    if not await callback_validate_inquiry(inquiry, callback, verify_blocked=False):
        return

    action_message = None
    if callback_data.action == InquiryAction.Reply.value:
        action_message = _("Reply message")
    elif callback_data.action == InquiryAction.BlockUser.value:
        action_message = _("Block user message")
    elif callback_data.action == InquiryAction.Close.value:
        action_message = _("Close message")

    await state.clear()
    await state.set_state(InquiryReplyForm.admin_reply)
    await state.update_data(
        reply_action=callback_data.action,
        inquiry_id=callback_data.inquiry_id,
        user_id=callback_data.user_id,
        message_id=callback_data.message_id,
        callback_message_id=callback.message.message_id,
        lang=callback_data.lang,
    )
    await callback.message.reply(
        _(
            "Type your <b>{action_message}</b> to Inquiry #R{inquiry_num:06d} or /cancel, language - <b>{lang}</b>.\n"
            "It will be delivered to the user @{username}."
        ).format(
            inquiry_num=inquiry.id,
            username=inquiry.username,
            action_message=action_message,
            lang=callback_data.lang.upper(),
        ),
    )
    await callback.answer()


@router.message(InquiryReplyForm.admin_reply, Command("cancel"))
async def admin_cancel_reply(message: Message, state: FSMContext):
    await state.clear()


@router.message(InquiryReplyForm.admin_reply)
async def admin_get_reply(message: Message, state: FSMContext):
    if message.chat.id != message.bot.app.admin_group_id:
        logger.warning(
            "Unathorized command: admin:reply, user_id: %s, username: %s",
            message.from_user.id,
            message.from_user.username,
        )
        return

    bot: _Bot = message.bot

    data = await state.get_data()
    reply_action = data["reply_action"]
    user_id = data["user_id"]
    message_id = data["message_id"]
    inquiry_id = data["inquiry_id"]
    _ = partial(gettext, data["lang"])
    try:
        inquiry = None
        try:
            if reply_action == InquiryAction.Close.value:
                inquiry = await bot.app.backend.inquiry_close(
                    inquiry_id=inquiry_id,
                    admin_user_id=message.from_user.id,
                    admin_message=message.text,
                )
            elif reply_action == InquiryAction.Reply.value:
                inquiry = await bot.app.backend.inquiry_get(inquiry_id=inquiry_id)
            elif reply_action == InquiryAction.BlockUser.value:
                inquiry = await bot.app.backend.inquiry_block(
                    inquiry_id=inquiry_id,
                    admin_user_id=message.from_user.id,
                    admin_message=message.text,
                    disable_to_hours=48,
                )
        except Exception as E:
            logger.warning(
                "Inquiry update error, user_id: %s, username: %s - %s: %s",
                message.from_user.id,
                message.from_user.username,
                type(E).__name__,
                E,
            )
            await message.reply(
                _("Failed to update Inquiry: {errorname}").format(errorname=type(E).__name__),
            )
            return

        action_message = None
        user_kb = False
        if reply_action == InquiryAction.Reply.value:
            action_icon = "📩"
            action_message = _("Replied")
            user_kb = True
        elif reply_action == InquiryAction.BlockUser.value:
            action_icon = "🚫"
            action_message = _("Blocked")
        elif reply_action == InquiryAction.Close.value:
            action_icon = "✅"
            action_message = _("Closed")

        # reply to user
        await message.bot.send_message(
            chat_id=user_id,
            text=_(
                "{action_icon} Your Inquiry #R{inquiry_num:06d} has been <b>{action_message}</b> with the following message\n\n{message}"
            ).format(
                inquiry_num=inquiry.id, message=message.text, action_message=action_message, action_icon=action_icon
            ),
            reply_to_message_id=message_id,
            reply_markup=(
                inquiry_user_kb(inquiry_id=inquiry_id, message_id=message.message_id, gettext=_) if user_kb else None
            ),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

        await message.reply(
            _(
                "{action_icon} Inquiry #R{inquiry_num:06d} from user @{username} has been <b>{action_message}</b>."
            ).format(
                username=inquiry.username,
                inquiry_num=inquiry.id,
                action_message=action_message,
                action_icon=action_icon,
            )
        )
    except Exception as e:
        await message.reply(f"Failed to send reply: {e}")
    await state.clear()


#
# InquiryForm
#
@router.callback_query(InquiryCallback.filter(F.action == InquiryAction.Cancel.value))
async def cancel_inquiry(callback: CallbackQuery, callback_data: InquiryCallback, state: FSMContext):
    inquiry_id = (await state.get_data()).get("inquiry_id")
    if callback_data.inquiry_id != inquiry_id:
        await context_lost(callback)
        return

    _ = partial(gettext, callback.from_user.language_code)
    await callback.message.answer(
        _("Your Inquiry has been cancelled."),
    )
    await callback.bot.edit_message_reply_markup(
        chat_id=callback.message.chat.id, message_id=callback.message.message_id, reply_markup=None
    )
    await callback.answer()
    await state.clear()


@router.callback_query(InquiryCallback.filter(F.action == InquiryAction.Submit.value))
async def submit_inquiry(callback: CallbackQuery, callback_data: InquiryCallback, state: FSMContext):
    inquiry_id = (await state.get_data()).get("inquiry_id")
    if callback_data.inquiry_id != inquiry_id:
        await context_lost(callback)
        return

    _ = partial(gettext, callback.from_user.language_code)
    bot: _Bot = callback.bot
    data = await state.get_data()
    data["message_id"] = callback.message.message_id
    inquiry_num = inquiry_id
    if bot.app.backend:
        try:
            inquiry_list = await bot.app.backend.inquiry_list(user_id=callback.from_user.id)
            if inquiry_list:
                inquiry = inquiry_list[0]
                await callback.message.answer(
                    _(
                        "⚠️ You already have an open inquiry #R{inquiry_num:06d}.\n"
                        "You must either <b>respond</b> to it or <b>close</b> it before submitting a new one."
                    ).format(inquiry_num=inquiry.id),
                    reply_markup=inquiry_user_kb(inquiry_id=inquiry.inquiry_id, message_id=0, gettext=_),
                )
                await callback.answer()
                return

            inquiry = await bot.app.backend.inquiry_create(user=callback.from_user, data=data)
            inquiry_num = inquiry.id
        except Exception as E:
            logger.warning(
                "Inquiry create error, user_id: %s, username: %s - %s: %s",
                callback.from_user.id,
                callback.from_user.username,
                type(E).__name__,
                E,
            )
            # await callback.message.answer(
            #     _("Submit Inquiry error: {errorname}").format(errorname=type(E).__name__),
            # )
            await callback.answer(
                text=_("Submit Inquiry error: {errorname}").format(errorname=type(E).__name__),
                show_alert=False,
                cache_time=30,
            )
            return

    address = data.get("nft_address")
    nft_info = ""
    if address:
        nft_info = (
            f'NFT: <code>{address}</code> - <a href="{bot.app.get_tonviewer_link(address)}">view on Tonviewer</a>\n\n'
        )
    inquiry_body = _(
        "🆕 Inquiry #R{inquiry_num:06d} from user @{username}:\n\n<b>{subject}</b>\n\n{nft_info}{message}"
    ).format(inquiry_num=inquiry_num, username=callback.from_user.username, nft_info=nft_info, **data)

    # Send to admin channel
    admin_message = await bot.send_message(
        bot.app.admin_group_id,
        inquiry_body,
        reply_markup=inquiry_admin_kb(
            inquiry_id=inquiry_id, message_id=callback.message.message_id, user=callback.from_user, gettext=_
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )

    await callback.message.edit_text(
        inquiry_body,
        reply_markup=inquiry_user_kb(inquiry_id=inquiry_id, message_id=admin_message.message_id, gettext=_),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()
    await state.clear()


@router.message(Command("inquiry"), F.chat.type == "private")
async def start_inquiry(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    inquiry_id = (await state.get_data()).get("inquiry_id")
    current_state = await state.get_state()
    if current_state is not None and current_state.startswith(f"{InquiryForm.__name__}:"):
        await message.answer(
            text=_("⚠️ You have already started filling out an inquiry. " 'If you want to start over press "Cancel".'),
            reply_markup=new_inquiry_kb(inquiry_id=inquiry_id, gettext=_),
        )
        return

    inquiry_id = random_inquiry_id()
    await state.update_data(inquiry_id=inquiry_id)

    await message.answer(
        text=_(
            "<b>You starting to fill new Inquiry.</b>\n\n"
            "Please provide following information:\n"
            " • Subject\n"
            " • Message\n"
            " • NFT address (optional)\n"
            " • Screenshot (optional)\n\n"
        ),
        reply_markup=new_inquiry_kb(inquiry_id=inquiry_id, gettext=_),
    )
    await message.answer(
        text=_("Enter your inquiry <b>Subject</b>:"),
    )
    await state.set_state(InquiryForm.subject)


@router.message(InquiryForm.subject)
async def get_subject(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    await state.update_data(subject=message.text)
    await message.answer(
        _("Enter your inquiry <b>Message</b>:"),
    )
    await state.set_state(InquiryForm.message)


@router.message(InquiryForm.message)
async def get_message(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    await state.update_data(message=message.text)
    await message.answer(
        _("Optionally you can send the <b>NFT address</b> or just /skip"),
    )
    await state.set_state(InquiryForm.nft_address)


@router.message(InquiryForm.nft_address, Command("skip"))
async def query_screenshot(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    await message.answer(
        _("Optionally you can send the <b>Screenshot</b> or just /skip"),
    )
    await state.set_state(InquiryForm.screenshot)


@router.message(InquiryForm.nft_address)
async def get_address(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    try:
        address = TonAddress(message.text.strip())
    except Exception:
        await message.answer(
            _("Provided input is not a valid TON Address. Please send the valid <b>NFT address</b> or just /skip"),
        )
        return
    await state.update_data(nft_address=address.b64url)
    await query_screenshot(message, state)


@router.message(InquiryForm.screenshot, F.photo)
async def get_screenshot(message: Message, state: FSMContext):
    await state.update_data(screenshot=message.photo[-1].file_id)
    await get_submit_inquiry(message, state)


@router.message(InquiryForm.screenshot, Command("skip"))
async def skip_screenshot(message: Message, state: FSMContext):
    await state.update_data(screenshot=None)
    await get_submit_inquiry(message, state)


async def get_submit_inquiry(message: Message, state: FSMContext):
    _ = partial(gettext, message.from_user.language_code)
    data = await state.get_data()
    await message.answer(
        _("Do you want to submit your Inquiry <b>{subject}</b>?").format(subject=data["subject"]),
        reply_markup=new_inquiry_kb(submit_btn=True, inquiry_id=data["inquiry_id"], gettext=_),
    )
