import asyncio
import unittest

from fastapi.testclient import TestClient
from freezegun import freeze_time

from NFTorrent.main import app, ws

client = TestClient(app, client=("127.0.0.1", 50000))


class TestTonlibManager(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        # Run an event loop to execute async setup
        cls.loop = asyncio.get_event_loop()
        cls.loop.run_until_complete(cls.asyncSetUpClass())

    @classmethod
    def tearDownClass(cls):
        cls.loop.run_until_complete(cls.asyncTearDownClass())
        cls.loop.close()

    @classmethod
    async def asyncSetUpClass(cls):
        await ws.startup()

    @classmethod
    async def asyncTearDownClass(cls):
        await ws.shutdown()

    async def asyncSetUp(self):
        while True:
            response = client.get("/api/v1/bootstrap")
            self.assertIn(response.status_code, [204, 502])
            if response.status_code == 204:
                break

    async def test_healthcheck(self):
        response = client.get("/healthcheck")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["node_id"], "dev-server")

        response = client.get("/api/v1/tonlib/state")
        self.assertEqual(response.status_code, 200)

        response = client.get("/api/v1/indexdb/state")
        self.assertEqual(response.status_code, 200)

        response = client.get("/api/v1/ipfs/state")
        self.assertEqual(response.status_code, 200)

    async def test_auth_web(self):
        response = client.get("/api/v1/account/authPayload")
        self.assertEqual(response.status_code, 200)
        payload = response.json().get("payload")
        self.assertIsNotNone(payload)

        auth_payload = {
            "account": {
                "address": "0:29739f3613b66d03a859590528183547eb8af669c53367530213609deaefbc52",
                "chain": -3,
                "public_key": "4e60c24b40405a827a5dda9d949c09b7cc169da88c617b3cc4b77ecb789662c5",
            },
            "proof": {
                "timestamp": 1763886648,
                "domain": "testnet.petsmem.site",
                "signature": "X0/ypVtAtgUYA9kmG9rvfrmt7S6ckzPMCT5FDKDUaDKPlh/3P+iONR+GbguHwQ41wOF7IKrFlkHoCdnOPn32Ag==",
                "payload": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOlsiTkZUb3JyZW50Il0sImV4cCI6MTc2Mzg4NjgxNiwidXNlciI6bnVsbH0.aeWD4Yc1rpV0A1qgYlZbiTaQ3RLEN6A06euS2NvW3IE",
            },
        }

        with freeze_time("2025-11-23T08:30:50", tz_offset=0):  # 1763886648 + 2 sec
            response = client.post("/api/v1/account/auth", json=auth_payload)

        self.assertEqual(response.status_code, 200)
        auth_result = response.json()
        self.assertEqual(auth_result["node"]["node_id"], "dev-server")
        self.assertEqual(
            auth_result["sess"],
            {
                "sub": "EQApc582E7ZtA6hZWQUoGDVH64r2acUzZ1MCE2Cd6u-8Ug4Y",
                "aud": ["NFTorrent"],
                "exp": 1765096250,
                "user": None,
            },
        )
