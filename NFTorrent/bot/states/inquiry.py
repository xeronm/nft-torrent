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
    lang: str
    action: str


class InquiryAction(Enum):
    Cancel = "cancel"
    Submit = "submit"
    Reply = "reply"
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
