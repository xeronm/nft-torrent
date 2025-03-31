from typing import Dict, Callable, Any, List
import time
import jwt
import os
from jwt.exceptions import InvalidTokenError

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from loguru import logger

class InvalidSubjectError(InvalidTokenError):
    pass

class NodeJWTBearer(HTTPBearer):

    def __init__(self, subject: str = None, 
                 jwt_secret: str = None, jwt_algorithm = None,
                 node_state: Callable[..., List[Dict]] = None, 
                 auto_error: bool = True, 
                 allow_local: bool = True,
                 real_ip_header: bool = True):
        super().__init__(auto_error=auto_error)
        self.allow_local = allow_local
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
        if self.real_ip_header:
            client_ip = request.headers.get('X-Real-IP', client_ip)
        if self.allow_local and client_ip == '127.0.0.1':
            return
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if credentials:
            try:
                self.verify_jwt_token(credentials.credentials, client_ip)
            except InvalidTokenError as E:
                logger.info('NodeJWTBearer: token validation error, token: {token}, client: {client_ip}, {exc}', 
                            token=credentials.credentials,
                            client_ip=client_ip, 
                            exc=str(E))
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
            
            return credentials.credentials
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization code")

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
            'tid': os.urandom(8).hex()
        }
        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        self._jwt_cache[audience] = (token, expires)
        return token


    def verify_jwt_token(self, jwtoken: str, client_ip: str):
        payload = jwt.decode(jwtoken, self.jwt_secret, 
                                audience=self.subject, 
                                algorithms=[self.jwt_algorithm])
        logger.debug('NodeJWTBearer:verify_jwt_token: decoded token, client: {client_ip}, payload: {payload}', 
                     client_ip=client_ip, payload=str(payload))

        subject = payload.get('sub', None)
        if not subject:
            raise InvalidSubjectError('Subject required')
        if subject != client_ip:
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
