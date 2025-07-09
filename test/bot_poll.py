import asyncio
import os

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from NFTorrent.bot import Backend, BotApp
from NFTorrent.bot.handlers import routers

token = os.environ["CI_BOT_TOKEN"]
dbpassword = os.environ["CI_DATABASE_PASSWORD"]


def main():

    async def __poll():
        bot = BotApp(
            token,
            admin_group_id=-1002890915463,
            backend=Backend(f"postgresql+psycopg2://postgres:{dbpassword}@172.16.1.1:6432/postgres"),
            torrent_file_size_limit=768 * 1024,
        )

        dp = Dispatcher(storage=MemoryStorage())

        dp.include_routers(*routers)

        await dp.start_polling(bot.bot)

    print("Starting test Bot...")
    asyncio.run(__poll())


main()
