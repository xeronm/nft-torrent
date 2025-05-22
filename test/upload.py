import os
import math
import io
import asyncio
import aiohttp
from PIL import Image


print(os.getcwd())

def _convert_image(buffer: bytes, size: int, format: str) -> bytes:
    img = Image.open(io.BytesIO(buffer))
    # 1. Resize min dimension to `size`
    x, y = img.size
    if x > size and y > size:
        # 1. Resize min dimension to `size`
        m, n = x/size, y/size
        x0 = y0 = size
        if m > n:
            x0 = math.ceil(x/n)
        elif n > m:
            y0 = math.ceil(y/m)
        img = img.resize([x0, y0])

    # 2. Crop square center
    x, y = img.size
    if x > size or y > size:
        x0 = y0 = 0
        if x > size:
            x0 = (x-size)//2
        if y > size:
            y0 = (y-size)//2
        img = img.crop((x0, y0, x0 + size, y0 + size))

    bufferOut = io.BytesIO()
    img.save(bufferOut, format)
    return bufferOut.getvalue()

def convert_file(filename: str):
    with open(filename, 'rb') as f:
        data = _convert_image(f.read(), 2000, 'webp')
    return data


test_files = [
    '../pets-memorial/assets/images/marcus-1.jpg',
    '../pets-memorial/assets/images/marcus-2.jpg',
    '../pets-memorial/assets/images/marcus-3.jpg',
    '../pets-memorial/assets/images/marcus-4.jpg'
]
test_url = 'http://127.0.0.1:8000/api/v1/nft/EQDf6Srtmxe-bTmwAf81o_e6fKT5jrg91Ai5B0i3t6PMIeMd/ipfs'

async def main(url: str = None, files = None):
    data = aiohttp.FormData()
    for filename in files:
        _, name = os.path.split(filename)
        name, _ = os.path.splitext(name)
        data.add_field('files', convert_file(filename), filename=f'{name}.webp', content_type='image/webp')

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data) as resp:
            print(resp.status)
            print(await resp.text())

asyncio.run(main(test_url, test_files))