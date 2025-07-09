from aiogram.types import InlineKeyboardButton, User
from aiogram.utils.keyboard import InlineKeyboardMarkup

from ..states.inquiry import InquiryAction, InquiryCallback, InquiryReplyCallback


def new_inquiry_kb(submit_btn: bool = False, inquiry_id: str = None, gettext=None):
    _ = gettext or (lambda x: x)
    row1 = [
        InlineKeyboardButton(
            text=_("Cancel"),
            callback_data=InquiryCallback(inquiry_id=inquiry_id, action=InquiryAction.Cancel.value).pack(),
        )
    ]
    if submit_btn:
        row1.append(
            InlineKeyboardButton(
                text=_("Submit"),
                callback_data=InquiryCallback(inquiry_id=inquiry_id, action=InquiryAction.Submit.value).pack(),
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[row1])


def inquiry_user_kb(inquiry_id: int = None, message_id: int = None, gettext=None):
    _ = gettext or (lambda x: x)
    row1 = [
        InlineKeyboardButton(
            text=_("Reply"),
            callback_data=InquiryReplyCallback(
                inquiry_id=inquiry_id, message_id=message_id, user_id=0, lang="", action=InquiryAction.Reply.value
            ).pack(),
        ),
        InlineKeyboardButton(
            text=_("Close"),
            callback_data=InquiryReplyCallback(
                inquiry_id=inquiry_id, message_id=message_id, user_id=0, lang="", action=InquiryAction.Close.value
            ).pack(),
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1])


def inquiry_admin_kb(inquiry_id: int = None, user: User = None, message_id: int = None, gettext=None):
    _ = gettext or (lambda x: x)
    row1 = [
        InlineKeyboardButton(
            text=_("Reply"),
            callback_data=InquiryReplyCallback(
                inquiry_id=inquiry_id,
                user_id=user.id,
                lang=user.language_code,
                message_id=message_id,
                action=InquiryAction.Reply.value,
            ).pack(),
        ),
        InlineKeyboardButton(
            text=_("Close"),
            callback_data=InquiryReplyCallback(
                inquiry_id=inquiry_id,
                user_id=user.id,
                lang=user.language_code,
                message_id=message_id,
                action=InquiryAction.Close.value,
            ).pack(),
        ),
        InlineKeyboardButton(
            text=_("Block"),
            callback_data=InquiryReplyCallback(
                inquiry_id=inquiry_id,
                user_id=user.id,
                lang=user.language_code,
                message_id=message_id,
                action=InquiryAction.BlockUser.value,
            ).pack(),
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1])
