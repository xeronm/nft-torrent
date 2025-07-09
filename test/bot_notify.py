import asyncio
import base64
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from NFTorrent.bot import BotApp, Backend, services
from NFTorrent.bot.handlers import inquiry
from NFTorrent.dbmodels import PetMemoryNft, PetsCollection, TgUser

token = os.environ["CI_BOT_TOKEN"]
dbpassword = os.environ["CI_DATABASE_PASSWORD"]

bot = BotApp(token)

user = TgUser(user_id=413537817)
nft = PetMemoryNft(
    address="EQAM38nXYgpT-3jFCpKai2aAZF0CuqZyeiH2F13lsKjl77KO",
    name="Marcus",
    birth_date="*",
    death_date="2024-11-15",
    fee_due_time=1781433492,
    image="ipfs://bafybeib356rlhshb7uxlxgwkk4qh4kyrm2ewp4n5qm2yxu4z2yjghevism/marcus-1.webp",
    description="He appeared in our lives on 08/19/2023. We noticed him a week earlier, on the way to the gym. A big, gray cat, thin as a skeleton, was running out of an abandoned private house, looked at people with piercing emerald eyes, and screamed. We tried to feed him, but that day I realized that if he did not run out at some day, I would not be able to forgive myself. An hour later, my wife and I caught him.\n"
    "It was a former domestic, neutered cat, 10-12 years old, with CKD. Then there were 15 months of struggle and joy of life, ups and downs, and dozens of visits to vets. Several times we thought that he wouldn't get out, but he had an iron will to live. However, on 11/15/2024, he passed away.",
    torrent_info=base64.b64decode("gASVxQMAAAAAAACMEE5GVG9ycmVudC5tb2RlbHOUjA5OZnRDb250ZW50SW5mb5STlCmBlH2UKIwIX19kaWN0X1+UfZQojARoYXNolIw7YmFmeWJlaWIzNTZybGhzaGI3dXhseGd3a2s0cWg0a3lybTJld3A0bjVxbTJ5eHU0ejJ5amdoZXZpc22UjARzaXpllEoeugkAjAVzdGF0ZZRoAIwPTmZ0Q29udGVudFN0YXRllJOUSwGFlFKUjAZkaWdlc3SUjBhzbmlhYmFrN3M2ZGNibTJseHRvMnN3ejeUjAVmaWxlc5RdlChoAIwOTmZ0Q29udGVudEZpbGWUk5QpgZR9lChoBX2UKIwEbmFtZZSMDW1hcmN1cy0xLndlYnCUaAlKtAcCAGgHjDtiYWZrcmVpYXpsc2kydmxncTZ3bHFoYzdieDR2c29jY283YWFzb3NsbnU3N3ppeTYza3ZlajZubjV6bZRoCmgOaA+MGDNoY3pvdmJ0c2JhbHEzZXFiYWR2cWVhZ5R1jBJfX3B5ZGFudGljX2V4dHJhX1+UTowXX19weWRhbnRpY19maWVsZHNfc2V0X1+Uj5QoaA9oCWgYaAeQjBRfX3B5ZGFudGljX3ByaXZhdGVfX5ROdWJoFCmBlH2UKGgFfZQoaBiMDW1hcmN1cy0yLndlYnCUaAlNMkJoB4w7YmFma3JlaWRweG13cjQ2eGNscDU2emh6ZHJnNGJsYnlzb3M1Y2p1bHkzN2Zkb3g2ZGNlNjdvcm9obGmUaApoDmgPjBhrcmFsZWN4ajNpZW42c2ZrNjZybWJsbDSUdWgcTmgdj5QoaA9oCWgYaAeQaB9OdWJoFCmBlH2UKGgFfZQoaBiMDW1hcmN1cy0zLndlYnCUaAlKNMADAGgHjDtiYWZrcmVpaG1rNTM1ZXYzdGU0dGdydHNrMzN5NGxtZzc1ZGRyMmdyem83dGZod3huaXRqZDQ2Z2h6ZZRoCmgOaA+MGGNsc2Z6ZTNmZ214ZXc2a3VpcTJibGl5dZR1aBxOaB2PlChoD2gJaBhoB5BoH051YmgUKYGUfZQoaAV9lChoGIwNbWFyY3VzLTQud2VicJRoCUoEsAMAaAeMO2JhZmtyZWliMjRvYjN4N29qZHhodDZkN2twYW1iYmdzeWJvNmhkcHI0ZmYzaXp5N2kycGJ1c25peGd5lGgKaA5oD4wYdmFuenFpbDNudGVrdDJjNWF4cGNqeTR6lHVoHE5oHY+UKGgPaAloGGgHkGgfTnViZXVoHE5oHY+UKGgPaAloEWgHkGgfTnViLg==")
)
collection = PetsCollection(address="EQDXmMnHdy75YldKGYfpm2eGTbkpHRq6CLjVIOJBdgjQt_Z9")


def main():

    async def __send():
        bot = BotApp(
            token,
            admin_group_id=-1002890915463,
            backend=Backend(f"postgresql+psycopg2://postgres:{dbpassword}@172.16.1.1:6432/postgres"),
        )

        await services.nft.nft_preview(bot, nft=nft, collection=collection, user=user, keyboard=False)
        await services.nft.notify_nft_minted(bot, nft=nft, collection=collection, user=user, keyboard=True)

    asyncio.run(__send())


main()