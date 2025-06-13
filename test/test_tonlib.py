import asyncio
import dataclasses
import unittest

from NFTorrent.collections import config
from NFTorrent.settings import TonlibSettings
from NFTorrent.tonlib import TonlibManager


class TestTonlibManager(unittest.IsolatedAsyncioTestCase):

    async def test_tonlib(self):
        self.tonlib = TonlibManager(
            TonlibSettings(
                max_liteservers=1,
                liteserver_config_path="https://ton.org/testnet-global.config.json",
                keystore=".tox/.ton_keystore",
                request_timeout=20,
            ),
            collection_config=config,
        )

        while not self.tonlib.workers[0].is_sync:
            await asyncio.sleep(1)

        result = self.tonlib.get_tonlib_state()
        self.assertGreater(
            dataclasses.asdict(self.tonlib.workers[0]).items(),
            {
                "is_alive": True,
                "is_sync": True,
                "is_enabled": True,
                "is_archival": False,
                "tasks_count": 0,
                "pending_tasks": 0,
            }.items(),
        )

        collection_data = await self.tonlib.get_collection_data(config.collections[0].address)
        self.assertEqual(
            dataclasses.asdict(collection_data),
            {
                "address": "EQAI_6RBqCUCGlNKRQOh_diuz8az2S_TY3IAHdozFTDDGs-9",
                "owner_address": "EQAG6X8FEs41ij3HEWms5BXuF_WBDb-uU4x8_HUguUCem8Ql",
                "next_item_index": collection_data.next_item_index,
                "collection_content": {
                    "type": "onchain",
                    "data": {
                        "image": "https://s.petsmem.site/c/EQAI_6RBqCUCGlNKRQOh_diuz8az2S_TY3IAHdozFTDDGs-9?q=image",
                        "uri": "https://s.petsmem.site/c/EQAI_6RBqCUCGlNKRQOh_diuz8az2S_TY3IAHdozFTDDGs-9?q=uri",
                        "name": "Test Collection",
                    },
                },
                "collection_info": {
                    "fee_storage": 0.05,
                    "fee_class_a": 0.025,
                    "fee_class_b": 0.05,
                    "balance": collection_data.collection_info.balance,
                    "balance_class_a": collection_data.collection_info.balance_class_a,
                    "balance_class_b": collection_data.collection_info.balance_class_b,
                    "fb_mode": 1,
                    "fb_uri": "https://s.petsmem.site/c/",
                },
            },
        )

        for name, address in config.collections[0].nft_samples.items():
            nft_data = await self.tonlib.get_nft_data(address)
            self.assertIsNotNone(nft_data)

        address = await self.tonlib.get_nft_item_address(config.collections[0].address, 0)
        self.assertIsNotNone(address)

        await self.tonlib.shutdown()
