import asyncio
import os

from NFTorrent.imageutils import convert_image

import aiohttp

print(os.getcwd())



def convert_file(filename: str):
    with open(filename, "rb") as f:
        data = convert_image(f.read(), 2000, "webp")
    return data


test_files = [
    "../pets-memorial/assets/images/marcus-1.jpg",
    "../pets-memorial/assets/images/marcus-2.jpg",
    "../pets-memorial/assets/images/marcus-3.jpg",
    "../pets-memorial/assets/images/marcus-4.jpg",
]
# test_url = 'http://127.0.0.1:8000/api/v1/nft/EQDf6Srtmxe-bTmwAf81o_e6fKT5jrg91Ai5B0i3t6PMIeMd/ipfs'
test_url = "http://127.0.0.1:8000/api/v1/nft/ipfs"


async def main(url: str = None, files=None):
    data = aiohttp.FormData()
    for filename in files:
        _, name = os.path.split(filename)
        name, _ = os.path.splitext(name)
        data.add_field("files", convert_file(filename), filename=f"{name}.webp", content_type="image/webp")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as resp:
            print(resp.status)
            print(await resp.text())


asyncio.run(main(test_url, test_files))
