import logging

from aiogram.filters import CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


def is_admin_command(message: Message, command: CommandObject) -> bool:
    if message.chat.id != message.bot.app.admin_group_id:
        logger.warning(
            "Unathorized message coomand: %s, user_id: %s, username: %s",
            command.text,
            message.from_user.id,
            message.from_user.username,
        )
        return False
    return True


def is_admin_callback(callback: CallbackQuery, callback_data: CallbackData) -> bool:
    if callback.message.chat.id != callback.bot.app.admin_group_id:
        logger.warning(
            "Unathorized message callback: %s, user_id: %s, username: %s",
            callback_data.pack(),
            callback.from_user.id,
            callback.from_user.username,
        )
        return False
    return True
