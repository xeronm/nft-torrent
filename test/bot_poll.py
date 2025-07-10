import asyncio
import os
import time

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from NFTorrent.bot import Backend, BotApp, StatisticsMiddleware
from NFTorrent.bot.handlers import routers
from NFTorrent.cache import MemoryCacheManager, MemoryCacheSettings
from NFTorrent.modelsbase import MeasurementStore, StatisticMeasurement

token = os.environ["CI_BOT_TOKEN"]
dbpassword = os.environ["CI_DATABASE_PASSWORD"]


def main():

    async def __poll():
        bot = BotApp(
            token,
            admin_group_id=-1002890915463,
            backend=Backend(
                f"postgresql+psycopg2://postgres:{dbpassword}@172.16.1.1:6432/postgres",
                cache_manager=MemoryCacheManager(MemoryCacheSettings(1024)),
            ),
            torrent_file_size_limit=768 * 1024,
        )

        dp = Dispatcher(storage=MemoryStorage())

        stats = MeasurementStore("NFTorrentBotDp", StatisticMeasurement)
        dp.include_routers(*routers)
        dp.message.middleware(StatisticsMiddleware(stats_store=stats))
        dp.callback_query.middleware(StatisticsMiddleware(stats_store=stats))

        await dp.start_polling(bot.bot)

        print(stats.as_influx(time.time()))
        print(bot.backend.stats.as_influx(time.time()))

    print("Starting test Bot...")
    asyncio.run(__poll())


main()
