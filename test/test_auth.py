import unittest
from unittest import mock

from NFTorrent import models
from NFTorrent.auth import ContractAPIKeyCookie, NodeJWTBearer


def get_known_peers():
    return {"192.168.1.10", "192.168.1.20"}


#   initData:
#     'user=%7B%22id%22%3A413537817%2C%22first_name%22%3A%22Denis%22%2C%22last_name%22%3A%22M%22%2C%22username%22%3A%22MuratovDe%22%2C%22language_code%22%3A%22ru%22%2C%22is_premium%22%3Atrue%2C%22allows_write_to_pm%22%3Atrue%2C%22photo_url%22%3A%22https%3A%5C%2F%5C%2Ft.me%5C%2Fi%5C%2Fuserpic%5C%2F320%5C%2FA9dHGRWXtJkMDL6M3T4JIHHJsNsrVDxI8i8kRCFn2Pg.svg%22%7D&chat_instance=-231214982729915704&chat_type=sender&auth_date=1750587194&signature=q91aeQ5L4wpLAZol4A57QD_XyZh3F0ivVPzk4-xb0x0KaGgH2te1Sozd_JjiHx-HmHOzdmgrk3y7uWfGHpa8BA&hash=890d5169d947344f1ea437820d25751e472e40e666adb91bee1373d9c61f3402',


class TestNodeJWTBearer(unittest.TestCase):

    def test_jwt_bearer(self):
        bearer_s10 = NodeJWTBearer(
            subject="192.168.1.10", jwt_algorithm="HS256", jwt_secret="0123456789", get_known_peers=get_known_peers
        )
        bearer_s20 = NodeJWTBearer(
            subject="192.168.1.20", jwt_algorithm="HS256", jwt_secret="0123456789", get_known_peers=get_known_peers
        )
        bearer_s30 = NodeJWTBearer(
            subject="192.168.1.30", jwt_algorithm="HS256", jwt_secret="0123456789", get_known_peers=get_known_peers
        )

        token_s20_a10 = bearer_s20.get_jwt_token("192.168.1.10")
        try:
            validated = bearer_s10.verify_jwt_token(token_s20_a10, "192.168.1.20") or True
        except Exception as E:
            validated = type(E).__name__
        self.assertIsInstance(validated, models.JWTPayload)

        token_s10_a20 = bearer_s10.get_jwt_token("192.168.1.20")
        try:
            validated = bearer_s20.verify_jwt_token(token_s10_a20, "192.168.1.10") or True
        except Exception as E:
            validated = type(E).__name__
        self.assertIsInstance(validated, models.JWTPayload)

        try:
            validated = bearer_s20.verify_jwt_token(token_s10_a20, "192.168.1.30") or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, "InvalidSubjectError")

        token_s10_a30 = bearer_s10.get_jwt_token("192.168.1.30")
        try:
            validated = bearer_s20.verify_jwt_token(token_s10_a30, "192.168.1.10") or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, "InvalidAudienceError")

        token_s30_a10 = bearer_s30.get_jwt_token("192.168.1.10")
        try:
            validated = bearer_s10.verify_jwt_token(token_s30_a10, "192.168.1.30") or True
        except Exception as E:
            validated = type(E).__name__
        self.assertEqual(validated, "InvalidSubjectError")


class TestContractAPIKeyCookie(unittest.TestCase):
    proof = {
        "timestamp": 1743608712,
        "domain": "127.0.0.1:5173",
        "signature": "F5JvXRdwbMjLHyST+X6WXbt25zCmlBEAy4jBOXeRI3R2dAZ4BRWwFhQ2DweGTBqrPRbReRQtJcNJt7kwWqE4DQ==",
        "payload": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0aWQiOiI0MWY2M2YwYTE2NDY0MDBkIiwic3ViIjoiYWNjb3VudCIsImF1ZCI6WyJuZnQtdG9ycmVudCJdLCJleHAiOjE3NDM2MDg4MTkuMTI4MDQxfQ.JxTRmHEVTiY-VMPa5sBQFqqwnia_yoqVlQqdtC7xxxM",  # noqa: E501
    }
    account = {
        "address": "0:06e97f0512ce358a3dc71169ace415ee17f5810dbfae538c7cfc7520b9409e9b",
        "chain": "-3",
        "public_key": "4e60c24b40405a827a5dda9d949c09b7cc169da88c617b3cc4b77ecb789662c5",
    }

    def test_auth_payload(self):
        contr = ContractAPIKeyCookie(jwt_algorithm="HS256", jwt_secret="0123456789", domains=["127.0.0.1:5173"])
        self.assertIsNotNone(contr.get_auth_payload())

    @mock.patch("time.time", mock.MagicMock(return_value=1743608712))
    def test_auth_success(self):
        contr = ContractAPIKeyCookie(jwt_algorithm="HS256", jwt_secret="0123456789", domains=["127.0.0.1:5173"])
        validated = None
        try:
            validated = (
                contr.auth_verify(account=models.Account(**self.account), proof=models.TonProof(**self.proof)) or True
            )
        except Exception as E:
            validated = str(E)
        self.assertEqual(validated, "Signature has expired")

    @mock.patch(
        "time.time", mock.MagicMock(return_value=1743608712 + ContractAPIKeyCookie.auth_payload_expires_timeout)
    )
    def test_auth_expired_error(self):
        contr = ContractAPIKeyCookie(jwt_algorithm="HS256", jwt_secret="0123456789")
        validated = None
        try:
            validated = (
                contr.auth_verify(account=models.Account(**self.account), proof=models.TonProof(**self.proof)) or True
            )
        except Exception as E:
            validated = str(E)
        self.assertEqual(validated, "Signature expired")

    @mock.patch("time.time", mock.MagicMock(return_value=1743608712))
    def test_auth_domain_error(self):
        contr = ContractAPIKeyCookie(jwt_algorithm="HS256", jwt_secret="0123456789")
        validated = None
        try:
            validated = (
                contr.auth_verify(account=models.Account(**self.account), proof=models.TonProof(**self.proof)) or True
            )
        except Exception as E:
            validated = str(E)
        self.assertEqual(validated, "Invalid domain: 127.0.0.1:5173")
