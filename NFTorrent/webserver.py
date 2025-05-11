import asyncio
import io
import json
import os
import random
import shutil
import tempfile
import time
from collections import Counter
from typing import Any, Dict, List

import aiohttp
from fastapi import UploadFile, status
from fastapi.exceptions import HTTPException
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from loguru import logger
from pyTON.cache import DisabledCacheManager
from pyTON.settings import RedisCacheSettings

from NFTorrent import exceptions
from NFTorrent.auth import (ContractAPIKeyCookie, NodeJWTBearer,
                            ServerResponseAuthError)
from NFTorrent.blockchain.address import parse_bag_id
from NFTorrent.cache import RedisCacheManager
from NFTorrent.exceptions import TorrentClientError
from NFTorrent.indexer.indexdb import IndexDb
from NFTorrent.models import HealthCheckResult
from NFTorrent.modelsbase import CollectionConfig
from NFTorrent.pyTON.manager import TonlibManager
from NFTorrent.settings import Settings
from NFTorrent.storage.manager import TonStorageCliManager


class Server:

    def __init__(self, settings: Settings = None, collection_config: CollectionConfig = None):
        self.settings = settings or Settings.from_environment()
        self.collection_config = collection_config or self.settings.webserver.collection_config
        self.tonlib: TonlibManager = None
        self.storage: TonStorageCliManager = None
        self.indexer: IndexDb = None
        self.peer_hostnames = {}
        self.loop = None
        self.stats = Counter()
        # self.resolver: aiodns.DNSResolver = None
        self.jwt_bearer = NodeJWTBearer(subject=self.settings.storage.storage_public_addr,
                                        jwt_secret=self.settings.webserver.jwt_secret,
                                        jwt_algorithm=self.settings.webserver.jwt_algorithm,
                                        node_state=self.get_node_state,
                                        real_ip_header=self.settings.webserver.real_ip_header,
                                        allow_networks=self.settings.webserver.allow_networks)

        self.jwt_session = ContractAPIKeyCookie(jwt_secret=self.settings.webserver.jwt_secret,
                                                jwt_algorithm=self.settings.webserver.jwt_algorithm,
                                                real_ip_header=self.settings.webserver.real_ip_header,
                                                domains=self.settings.webserver.twa_domains,
                                                allow_networks=self.settings.webserver.allow_networks)

    def get_node_state(self):
        return self.storage.get_cached_node_state()

    async def startup(self):
        self.loop = loop = asyncio.get_event_loop()
        logger.warning('Server startup initiated...')
        logger.warning("Parameters:\n"
                       " - webserver.allow_networks: {networks}\n"
                       " - webserver.api_root_path: {api_root}\n"
                       " - webserver.storage_public_addr: {addr}\n"
                       " - webserver.twa_domains: {domains}\n"
                       " - storage.storage_db_path: {dbpath}\n"
                       " - storage.storage_temp_dir: {tempdir}\n"
                       " - storage.min_redundancy: {redundancy}\n"
                       " - cache.enabled: {cache_enabled}\n"
                       " - indexdb.enabled: {indexdb_enabled}\n",
                       addr=self.settings.storage.storage_public_addr,
                       api_root=self.settings.webserver.api_root_path,
                       domains=self.settings.webserver.twa_domains,
                       networks=self.settings.webserver.allow_networks,
                       dbpath=self.settings.storage.storage_db_path,
                       tempdir=self.settings.storage.storage_temp_dir,
                       redundancy=self.settings.storage.min_redundancy,
                       cache_enabled=self.settings.cache.enabled,
                       indexdb_enabled=self.settings.indexdb.enabled)

        cache_manager = None
        if self.settings.cache.enabled:
            if isinstance(self.settings.cache, RedisCacheSettings):
                cache_manager = RedisCacheManager(self.settings.cache)
            else:
                raise RuntimeError('Only Redis cache supported')
        else:
            cache_manager = DisabledCacheManager()

        if self.settings.tonlib.liteserver_config_path:
            self.tonlib = TonlibManager(tonlib_settings=self.settings.tonlib,
                                        dispatcher=None,
                                        cache_manager=cache_manager,
                                        loop=loop,
                                        collection_config=self.collection_config)

            if self.settings.indexdb.enabled:
                self.indexer = IndexDb(self.settings.indexdb,
                                       cache_manager=cache_manager,
                                       loop=loop,
                                       tonlib=self.tonlib,
                                       collection_config=self.collection_config)
        else:
            logger.warning("Tonlib disabled, liteserver_config required")

        if self.settings.storage.num_workers:
            self.storage = TonStorageCliManager(self.settings.storage,
                                                dispatcher=None,
                                                cache_manager=cache_manager,
                                                tonlib=self.tonlib,
                                                remote_call=self.remote_call,
                                                loop=loop)
        else:
            logger.warning("Storage disabled, num_workers required")

        await asyncio.sleep(3)  # wait for manager to spawn all workers and report their status

    async def shutdown(self):
        logger.warning('Server shutdown initiated...')
        if self.indexer is not None:
            await self.indexer.shutdown()
        await asyncio.wait([
            self.tonlib.shutdown(),
            self.storage.shutdown(),
        ], return_when=asyncio.ALL_COMPLETED)

    def _get_peer_uri(self, host: str, path: str):
        authority = f'{host}:{self.settings.webserver.port}' if self.settings.webserver.port else host
        api_root = self.settings.webserver.remote_api_root or self.settings.webserver.api_root_path
        if api_root[-1] == '/' and path[0] == '/':
            path = api_root + path[1:]
        elif api_root[-1] != '/' and path[0] != '/':
            path = api_root + '/' + path
        else:
            path = api_root + path
        schema = 'https' if self.settings.webserver.enable_ssl else 'http'
        return f'{schema}://{authority}{path}'

    def _get_peer_headers(self, host: str):
        return {
            'Authorization': 'Bearer ' + self.jwt_bearer.get_jwt_token(host)
        }

    # API
    async def get_healthcheck(self) -> HealthCheckResult:
        tonlib_state = sum([1 for x in self.tonlib.get_workers_state().values() if x['is_working']])
        stotage_state = sum([1 for x in self.storage.get_workers_state().values() if x['is_healthy']])

        return HealthCheckResult(
            tonlib=bool(tonlib_state),
            storage=bool(stotage_state),
            redundancy=bool(len(await self.storage.get_node_state()) >= self.settings.storage.min_redundancy),
            load=round(self.storage.storage_lru.size * 100 / self.storage.settings.storage_max_size, 2)
        )

    async def remote_call(self, host: str, remote_path: str):
        # host = await self._get_peer_hostname(peer["ip_str"])
        result = {}
        logger.info("Call storage remote peer, host: {host}, remote_path: {remote_path}",
                    host=host, remote_path=remote_path)
        async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=self.settings.webserver.request_timeout)
                        ) as session:
            try:
                self.stats['call_remote'] += 1
                async with await session.get(self._get_peer_uri(host, remote_path),
                                             headers=self._get_peer_headers(host),
                                             verify_ssl=self.settings.webserver.verify_ssl,
                                             allow_redirects=False) as resp:
                    if self.settings.webserver.bearer_auth_response:
                        await self.jwt_bearer.response_credentials(resp, host)
                    result['status'] = resp.status
                    result['response'] = await resp.read()
                    result['headers'] = resp.headers
            except Exception as E:
                self.stats['call_remote_error'] += 1
                if isinstance(E, ServerResponseAuthError):
                    self.stats['remote_auth_error'] += 1
                result['error'] = str(E)
                logger.warning("Call storage remote peer error, host: {host}, remote_path: {remote_path}, exc: {exc}",  # noqa: E501
                               host=host, remote_path=remote_path, exc=str(E))

        token = self.jwt_bearer.get_jwt_token(host)
        return result, token

    async def get_default_image(self, address: str):
        headers = {"Cache-Control": "public, max-age=3600"}
        nft_collection = self.collection_config.get_collection(address)
        if nft_collection is not None:
            return FileResponse(nft_collection.image, headers=headers)

        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content

        image = nft_content.image()
        if nft_content.bag_id() and image and image[0] == ":":
            return await self.storage.get_torrent_content(address, bag_id=nft_content.bag_id(), digest=image[1:])
        if image:
            return RedirectResponse(image)
        if nft_content.image_data():
            response = StreamingResponse(io.BytesIO(nft_content.image_data()),
                                         media_type='image/webp', headers=headers)
            return response

        # TODO: Generate dynamic default image with pets Name
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)


    async def get_nft_torrent_content(self,
                                      address: str = None,
                                      file_path: str = None,
                                      digest: str = None):
        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content
        bag_id = None
        if nft_content is not None:
            bag_id = nft_content.bag_id()
        if bag_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return self.storage.get_torrent_content(bag_id=bag_id, file_path=file_path, digest=digest)