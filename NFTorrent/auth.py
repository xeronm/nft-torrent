import base64
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import logging
import struct
import time
from collections.abc import Callable
from datetime import datetime
from email.utils import format_datetime
from http.cookies import Morsel
from typing import Any, Literal

import jwt
from aiohttp import ClientResponse
from fastapi import HTTPException, Request, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from nacl.signing import VerifyKey

from NFTorrent import models
from NFTorrent.modelsbase import TonAddress

logger = logging.getLogger(__name__)


class InvalidSubjectError(InvalidTokenError):
    pass


class SignatureVerificationError(Exception):
    pass


class ServerResponseAuthError(Exception):
    pass


class NodeJWTBearer(HTTPBearer):
    response_header = "X-Peer-Bearer-Token"

    def __init__(
        self,
        subject: str = None,
        jwt_secret: str = None,
        jwt_algorithm: str = None,
        get_known_peers: Callable[..., set[str]] = None,
        auto_error: bool = True,
        allow_networks: list[str] = None,
        real_ip_header: bool = True,
    ):
        super().__init__(auto_error=auto_error)
        self.allow_networks = [ipaddress.ip_network(x) for x in allow_networks or []]
        self.real_ip_header = real_ip_header
        self.subject = subject.split(":")[0]
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.get_known_peers = get_known_peers
        self._jwt_cache = {}

    async def __call__(self, request: Request):
        client_ip = request.client.host
        real_ip = request.headers.get("X-Real-IP")
        logger.debug("NodeJWTBearer: Authorization request, real_ip: %s, host: %s", real_ip, client_ip)
        if self.real_ip_header:
            client_ip = request.headers.get("X-Real-IP", client_ip)
        if self.allow_networks and [True for x in self.allow_networks if ipaddress.ip_address(client_ip) in x]:
            request.state.bearer_auth_client_ip = client_ip
            return {}

        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if credentials is None:
            return None
        try:
            payload = self.verify_jwt_token(credentials.credentials, client_ip)
        except InvalidTokenError as E:
            logger.info(
                "NodeJWTBearer: token validation error, token: %s, client_ip: %s - %s: %s",
                credentials.credentials,
                client_ip,
                type(E).__name__,
                E,
            )
            if self.auto_error:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired token") from E
            else:
                return None

        request.state.bearer_auth_client_ip = client_ip
        return payload

    async def response_credentials(self, response: ClientResponse, server_ip: str):
        response_token = response.headers.get(self.response_header)
        if not response_token:
            if self.auto_error:
                raise ServerResponseAuthError("Response not authenticated")
            else:
                return None
        try:
            payload = self.verify_jwt_token(response_token, server_ip)
        except InvalidTokenError as E:
            logger.info(
                "NodeJWTBearer: token validation error, token: %s, server_ip: %s - %s: %s",
                response_token,
                server_ip,
                type(E).__name__,
                E,
            )
            if self.auto_error:
                raise ServerResponseAuthError("Invalid or expired token") from E
            else:
                return None
        return payload

    def get_jwt_token(self, audience: str) -> dict[str, Any]:
        token, expires = self._jwt_cache.get(audience, (None, None))
        curr_time = int(time.time())
        if expires is not None and expires > curr_time + 60:
            return token

        expires = curr_time + 3600
        payload = {
            "sub": self.subject,
            "aud": [audience],
            "exp": expires,
        }
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        self._jwt_cache[audience] = (token, expires)
        return token

    def verify_jwt_token(self, jwtoken: str, subject_ip: str):
        payload = jwt.decode(jwtoken, self.jwt_secret, audience=self.subject, algorithms=[self.jwt_algorithm])
        logger.debug(
            "NodeJWTBearer: decoded token, subject: %s, payload: %s",
            subject_ip,
            str(payload),
        )

        subject = payload.get("sub", None)
        if not subject:
            raise InvalidSubjectError("Subject required")
        if subject != subject_ip:
            raise InvalidSubjectError("Subject not match client address")

        _known_peers = self.get_known_peers() if self.get_known_peers is not None else None
        if subject != self.subject and (_known_peers is None or subject not in _known_peers):
            raise InvalidSubjectError("Subject not known")
        return models.JWTPayload(**payload)


class ContractAPIKeyCookie(APIKeyCookie):
    audience = "NFTorrent"
    cookie_name = "NFTorrent"
    auth_payload_expires_timeout = 180
    session_token_timeout = 14 * 86400

    def __init__(
        self,
        jwt_secret: str = None,
        jwt_algorithm: str = None,
        bot_token: str = None,
        domains: list[str] = None,
        allow_networks: list[str] = None,
        real_ip_header: bool = True,
    ):
        super().__init__(name=self.cookie_name, auto_error=False)
        self.domains = set(domains or [])
        self.allow_networks = [ipaddress.ip_network(x) for x in allow_networks or []]
        self.real_ip_header = real_ip_header
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.bot_secret = None
        if bot_token:
            self.bot_secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()

    async def __call__(self, request: Request):
        client_ip = request.client.host
        real_ip = request.headers.get("X-Real-IP")
        logger.debug(
            "ContractAPIKeyCookie: Authorization request, real_ip: %s, host: %s",
            real_ip,
            client_ip,
        )
        if self.real_ip_header:
            client_ip = request.headers.get("X-Real-IP", client_ip)

        api_key: str = await super().__call__(request)
        if not api_key:
            if self.allow_networks and [True for x in self.allow_networks if ipaddress.ip_address(client_ip) in x]:
                return
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

        try:
            payload = jwt.decode(api_key, self.jwt_secret, audience=self.audience, algorithms=[self.jwt_algorithm])
        except InvalidTokenError as E:
            logger.info(
                "ContractAPIKeyCookie: token validation error, token: %s, client_ip: %s, host: %s - %s: %s",  # noqa: E501
                api_key,
                client_ip,
                request.client.host,
                type(E).__name__,
                E,
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired token") from E

        return models.JWTPayload(**payload)

    def validate_init_data(self, init_data: dict) -> dict:
        """
        Validates Telegram WebApp.initData string.

        :param init_data: Raw initData from Telegram (query string format)
        :return: Parsed dict if valid, else raises ValueError
        """
        if "hash" not in init_data:
            raise ValueError("Missing 'hash' attribute")

        try:
            received_hash = init_data["hash"]

            # Data-check-string is a chain of all received fields, sorted alphabetically,
            # in the format key=<value> with a line feed character ('\n', 0x0A) used as separator
            sorted_fields = sorted([(k, v) for k, v in init_data.items() if k != "hash"])
            data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_fields)

            computed_hash = hmac.new(self.bot_secret, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(computed_hash, received_hash):
                raise ValueError("Invalid signature")
        except Exception as E:
            raise ValueError(f"initData validation failed: {str(E)}") from E

    def get_auth_payload(self, init_data: dict = None) -> str:
        user = None

        attrmap = {
            "id": "id",
            "username": "name",
            "language_code": "lang",
            "is_premium": "prem"
        }
        if init_data and self.bot_secret:
            try:
                self.validate_init_data(init_data)
                user = {
                    attrmap[k]: v
                    for k, v in json.loads(init_data.get("user", {})).items()
                    if k in attrmap
                }
            except ValueError as E:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(E)) from E

        expires = int(time.time()) + self.auth_payload_expires_timeout
        payload = {"aud": [self.audience], "exp": expires, "user": user}
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        return token

    def auth_verify(self, account: models.Account, proof: models.TonProof, public_key: str = None):
        curr_time = time.time()
        raw_address = TonAddress(account.address).raw_form
        wc, whash = raw_address.split(":", maxsplit=2)

        if curr_time >= proof.timestamp + self.auth_payload_expires_timeout:
            raise SignatureVerificationError("Signature expired")

        if proof.domain not in self.domains:
            raise SignatureVerificationError(f"Invalid domain: {proof.domain}")

        message = b"".join(
            [
                b"ton-proof-item-v2/",
                struct.pack(">i32s", int(wc, 10), bytes.fromhex(whash)),
                struct.pack("<I", len(proof.domain)),
                proof.domain.encode(),
                struct.pack("<Q", proof.timestamp),
                proof.payload.encode(),
            ]
        )

        msg_hash = hashlib.sha256(message).digest()

        full_message = b"".join([b"\xff\xffton-connect", msg_hash])

        try:
            verify_key = VerifyKey(bytes.fromhex(public_key or account.public_key))
            verify_key.verify(hashlib.sha256(full_message).digest(), base64.b64decode(proof.signature))
        except Exception as E:
            raise SignatureVerificationError("Signature verification failed") from E

        return jwt.decode(proof.payload, self.jwt_secret, audience=self.audience, algorithms=[self.jwt_algorithm])

    def auth_session(self, account: models.Account, proof: models.TonProof, public_key: str = None):
        try:
            jwt_token = self.auth_verify(account, proof, public_key)
        except (InvalidTokenError, SignatureVerificationError) as E:
            logger.warning(
                "ContractAPIKeyCookie: signature validation error, account: %s - %s: %s",
                account.address,
                type(E).__name__,
                E,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired signature") from E

        expires = int(time.time()) + self.session_token_timeout
        payload = {"sub": account.address, "aud": [self.audience], "exp": expires, "user": jwt_token.get("user")}
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        return models.JWTPayload(**payload), token


Morsel._reserved["partitioned"] = "Partitioned"
Morsel._flags.add("partitioned")


def set_cookie(
    request: Request,
    key: str,
    value: str = "",
    max_age: int | None = None,
    expires: datetime | str | int | None = None,
    path: str | None = "/",
    domain: str | None = None,
    secure: bool = False,
    httponly: bool = False,
    samesite: Literal["lax", "strict", "none"] | None = "lax",
    partitioned: bool = False,
) -> None:
    cookie: http.cookies.BaseCookie[str] = http.cookies.SimpleCookie()
    cookie[key] = value
    if max_age is not None:
        cookie[key]["max-age"] = max_age
    if expires is not None:
        if isinstance(expires, datetime):
            cookie[key]["expires"] = format_datetime(expires, usegmt=True)
        else:
            cookie[key]["expires"] = expires
    if path is not None:
        cookie[key]["path"] = path
    if domain is not None:
        cookie[key]["domain"] = domain
    if secure:
        cookie[key]["secure"] = True
    if httponly:
        cookie[key]["httponly"] = True
    if samesite is not None:
        assert samesite.lower() in [
            "strict",
            "lax",
            "none",
        ], "samesite must be either 'strict', 'lax' or 'none'"
        cookie[key]["samesite"] = samesite
    if partitioned:
        cookie[key]["partitioned"] = True
    cookie_val = cookie.output(header="").strip()
    request.raw_headers.append((b"set-cookie", cookie_val.encode("latin-1")))
