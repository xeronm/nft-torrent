from typing import Dict, Callable, Any, List
import time
import jwt
import ipaddress
import hashlib
import struct
import base64
from jwt.exceptions import InvalidTokenError
from aiohttp import ClientResponse

from nacl.signing import VerifyKey
from pydantic import BaseModel
from fastapi import Request, HTTPException, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyCookie

from pytonlib.utils.address import detect_address
from NFTorrent import models

from loguru import logger


class JWTPayload(BaseModel):
    sub: str
    aud: List[str]
    exp: int

class InvalidSubjectError(InvalidTokenError):
    pass

class SignatureVerificationError(Exception):
    pass

class ServerResponseAuthError(Exception):
    pass

class NodeJWTBearer(HTTPBearer):
    response_header = "X-Peer-Bearer-Token"

    def __init__(self, subject: str = None, 
                 jwt_secret: str = None, jwt_algorithm = None,
                 node_state: Callable[..., List[Dict]] = None, 
                 auto_error: bool = True, 
                 allow_networks: List[str] = None,
                 real_ip_header: bool = True):
        super().__init__(auto_error=auto_error)
        self.allow_networks = [ipaddress.ip_network(x) for x in allow_networks or []]
        self.real_ip_header = real_ip_header
        self.subject = subject.split(':')[0]
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.node_state = node_state
        self._node_state = None
        self._node_state_map = None
        self._jwt_cache = {}

    async def __call__(self, request: Request):
        client_ip = request.client.host
        real_ip = request.headers.get('X-Real-IP')
        logger.debug('NodeJWTBearer: Authorization request, real_ip: {real_ip}, host: {host}', real_ip=real_ip, host=client_ip)
        if self.real_ip_header:
            client_ip = request.headers.get('X-Real-IP', client_ip)
        if self.allow_networks and [True for x in self.allow_networks if ipaddress.ip_address(client_ip) in x]:
            request.state.bearer_auth_client_ip = client_ip
            return {}
        
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if credentials is None:
            return None
        try:
            payload = self.verify_jwt_token(credentials.credentials, client_ip)
        except InvalidTokenError as E:
            logger.info('NodeJWTBearer: token validation error, token: {token}, client_ip: {client_ip}, {exc}', 
                        token=credentials.credentials,
                        client_ip=client_ip, 
                        exc=str(E))
            if self.auto_error:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired token")
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
            logger.info('NodeJWTBearer: token validation error, token: {token}, server_ip: {server_ip}, {exc}', 
                        token=response_token,
                        server_ip=server_ip, 
                        exc=str(E))
            if self.auto_error:
                raise ServerResponseAuthError("Invalid or expired token")
            else:
                return None
        return payload

    def get_jwt_token(self, audience: str) -> Dict[str, Any]:
        token, expires = self._jwt_cache.get(audience, (None, None))
        curr_time = time.time()
        if expires is not None and expires > curr_time + 60:
            return token
        
        expires = curr_time + 3600
        payload = {
            'sub': self.subject,
            'aud': [audience],
            'exp': expires,
        }
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        self._jwt_cache[audience] = (token, expires)
        return token

    def verify_jwt_token(self, jwtoken: str, subject_ip: str):
        payload = jwt.decode(jwtoken, self.jwt_secret, 
                             audience=self.subject, 
                             algorithms=[self.jwt_algorithm])
        logger.debug('NodeJWTBearer:verify_jwt_token: decoded token, subject: {subject_ip}, payload: {payload}', 
                     subject_ip=subject_ip, payload=str(payload))

        subject = payload.get('sub', None)
        if not subject:
            raise InvalidSubjectError('Subject required')
        if subject != subject_ip:
            raise InvalidSubjectError('Subject not match client address')
        
        _node_state = self.node_state()
        if not _node_state is self._node_state:
            self._node_state = _node_state
            self._node_state_map = {
                item['ip_str'].split(':')[0]: item['adnl_id'] 
                for item in self._node_state
            }
            logger.debug('NodeJWTBearer:verify_jwt_token: update node table: {table}', table=str(self._node_state_map))

        if subject != self.subject and subject not in self._node_state_map:
            raise InvalidSubjectError('Subject not known')
        return JWTPayload(**payload)


class ContractAPIKeyCookie(APIKeyCookie):
    audience = 'NFTorrent'
    cookie_name = 'NFTorrent'
    auth_payload_expires_timeout = 180
    session_token_timeout = 14 * 86400

    def __init__(self, 
                 jwt_secret: str = None, jwt_algorithm = None,
                 domains: List[str] = None,
                 auto_error: bool = True, 
                 allow_networks: List[str] = None,
                 real_ip_header: bool = True):
        super().__init__(name=self.cookie_name, auto_error=auto_error)
        self.domains = set(domains or [])
        self.allow_networks = [ipaddress.ip_network(x) for x in allow_networks or []]
        self.real_ip_header = real_ip_header
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm

    async def __call__(self, request: Request):
        client_ip = request.client.host
        real_ip = request.headers.get('X-Real-IP')
        logger.debug('ContractAPIKeyCookie: Authorization request, real_ip: {real_ip}, host: {host}', real_ip=real_ip, host=client_ip)
        if self.real_ip_header:
            client_ip = request.headers.get('X-Real-IP', client_ip)
        if self.allow_networks and [True for x in self.allow_networks if ipaddress.ip_address(client_ip) in x]:
            return

        api_key: str = await super().__call__(request)

        try:
            payload = jwt.decode(api_key, self.jwt_secret, 
                                audience=self.audience, 
                                algorithms=[self.jwt_algorithm])        
        except InvalidTokenError as E:
            logger.info('ContractAPIKeyCookie: token validation error, token: {token}, client_ip: {client_ip}, host: {host}, {exc}', 
                        token=api_key,
                        client_ip=client_ip,
                        host=request.client.host,
                        exc=str(E))
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired token")
        
        return JWTPayload(**payload)
        
    def get_auth_payload(self) -> str:
        expires = time.time() + self.auth_payload_expires_timeout
        payload = {
            'aud': [self.audience],
            'exp': expires
        }
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        return token

    def auth_verify(self, account: models.Account, proof: models.TonProof, public_key: str = None):
        curr_time = time.time()
        raw_address = detect_address(account.address)['raw_form']
        wc, whash = raw_address.split(':', maxsplit=2)

        if curr_time >= proof.timestamp + self.auth_payload_expires_timeout:
            raise SignatureVerificationError("Signature expired")

        if not proof.domain in self.domains:
            raise SignatureVerificationError("Invalid domain")

        message = b''.join([
            b'ton-proof-item-v2/',
            struct.pack('>i32s', int(wc, 10), bytes.fromhex(whash)), 
            struct.pack('<I', len(proof.domain)),
            proof.domain.encode(),
            struct.pack('<Q', proof.timestamp),
            proof.payload.encode()
        ])

        msg_hash = hashlib.sha256(message).digest()

        full_message = b''.join([
            b'\xff\xffton-connect',
            msg_hash
        ])

        try:
            verify_key = VerifyKey(bytes.fromhex(public_key or account.public_key))
            verify_key.verify(hashlib.sha256(full_message).digest(), base64.b64decode(proof.signature))
        except Exception as E:
            raise SignatureVerificationError("Signature verification failed")

        payload = jwt.decode(proof.payload, self.jwt_secret, 
                            audience=self.audience, 
                            algorithms=[self.jwt_algorithm])
   
    def auth_session(self, account: models.Account, proof: models.TonProof, public_key: str = None):
        try:
            self.auth_verify(account, proof, public_key)
        except (InvalidTokenError, SignatureVerificationError) as E:
            logger.warning('ContractAPIKeyCookie: signature validation error, account: {address}, {exc}', 
                        address=account.address, 
                        exc=str(E))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired signature")
        
        expires = time.time() + self.session_token_timeout
        payload = {
            'sub': account.address,
            'aud': [self.audience],            
            'exp': expires
        }
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        response = Response(status_code=status.HTTP_200_OK)
        response.set_cookie(self.cookie_name, token, expires=expires, secure=True, httponly=True)
        return response
    

    # NFTorrent=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0aWQiOiI0NjA0MGFhYSIsInN1YiI6IkVRQUc2WDhGRXM0MWlqM0hFV21zNUJYdUYvV0JEYit1VTR4OC9IVWd1VUNlbThRbCIsImF1ZCI6WyJORlRvcnJlbnQiXSwiZXhwIjoxNzQ0ODI0Njc3LjI4NDk5MjJ9.nW-eraHFWlJKMYaBRgN3PYpNYT6OS6zx386BqKTT44E; 
    # expires=1744824677.2849922; HttpOnly; Path=/; SameSite=lax; Secure