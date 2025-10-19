from enum import Enum

from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup


class InquiryCallback(CallbackData, prefix="inquiry"):
    inquiry_id: str
    action: str


class InquiryReplyCallback(CallbackData, prefix="inquiry"):
    inquiry_id: str
    user_id: int
    message_id: int
    action: str


class InquiryAction(Enum):
    Cancel = "cancel"
    Submit = "submit"
    NextStep = "next"
    Reply = "reply"
    ReplyCancel = "replyCancel"
    Close = "close"
    BlockUser = "block"


class InquiryForm(StatesGroup):
    subject = State()
    message = State()
    nft_address = State()
    screenshot = State()
    confirmation = State()


class InquiryReplyForm(StatesGroup):
    admin_reply = State()
    user_reply = State()
