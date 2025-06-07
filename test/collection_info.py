import asyncio
from pathlib import Path

import requests
from pytonlib import TonlibClient


async def main():
    loop = asyncio.get_running_loop()
    ton_config = requests.get("https://ton.org/testnet-global.config.json").json()

    # create keystore directory for tonlib
    keystore_dir = ".tox/.ton_keystore"
    Path(keystore_dir).mkdir(parents=True, exist_ok=True)

    # init TonlibClient
    client = TonlibClient(
        ls_index=0,  # choose LiteServer index to connect
        config=ton_config,
        keystore=keystore_dir,
        cdll_path=None,
        tonlib_timeout=60,
        verbosity_level=1,
        loop=loop,
    )

    # init tonlibjson
    await client.init()

    await asyncio.sleep(3)
    # reading masterchain info
    # masterchain_info = await client.get_masterchain_info()
    # print(masterchain_info)
    for address in [
        "EQCq3q4Oi6nxLGA399SXlUv6XR8sAECm_TPIl-kZRY6rvIvc",
        "EQA9qLAEkjSWrmKRg8FjEX22TnRj7Urg_xUsDqcriQnK7xL2",
    ]:
        print(f"Collection: {address}")
        try:
            collection_data = await client.raw_run_method(address, "get_info", [])
            print(collection_data)
        except Exception as E:
            print(f"!!!!! Error {E}")

    # closing session
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
