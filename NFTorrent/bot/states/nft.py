from aiogram.fsm.state import State, StatesGroup


class NftForm(StatesGroup):
    address = State()
