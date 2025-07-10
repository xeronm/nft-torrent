from typing import Any
from collections.abc import Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message

from NFTorrent.modelsbase import MeasurementStore, MethodStatisticTags

class StatisticsMiddleware(BaseMiddleware):
    def __init__(self, stats_store: MeasurementStore = None) -> None:
        self.stats_store = stats_store

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any]
    ) -> Any:
        key = MethodStatisticTags(data['handler'].callback.__name__)
        with self.stats_store[key]:
            return await handler(event, data)

__all__ = ["StatisticsMiddleware"]