from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from NFTorrent.dbmodels import PetMemoryNft, PetsCollection

from ..main import BotApp


def main_nft_kb(app: BotApp, nft: PetMemoryNft, collection: PetsCollection, donate_btn: bool = False, gettext=None):
    _ = gettext or (lambda x: x)

    gglink = app.get_getgems_link(collection.address, nft.address)
    ipfslink = app.get_ipfs_link(nft.image)

    keyboard_row = [
        InlineKeyboardButton(text=_("View"), web_app=WebAppInfo(url=app.get_petsmem_link(nft.address))),
        InlineKeyboardButton(text=_("Getgems"), url=gglink),
    ]

    if ipfslink:
        keyboard_row += (InlineKeyboardButton(text=_("IPFS.io"), url=ipfslink),)

    keyboard = [keyboard_row]
    if donate_btn:
        keyboard = [
            InlineKeyboardButton(
                text=_("Donate (Renew storage)"),
                web_app=WebAppInfo(url=app.get_petsmem_link(nft.address, {"doante": 1})),
            )
        ] + keyboard

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
