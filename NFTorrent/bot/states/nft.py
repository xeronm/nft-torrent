from enum import Enum

from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup


class NftFormAction(Enum):
    Cancel = "cancel"


class NftFormCallback(CallbackData, prefix="nftform"):
    action: str


class NftForm(StatesGroup):
    address = State()
