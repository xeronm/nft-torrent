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
from pytonlib.utils.address import prepare_address

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


class BagWriteLock:

    def __init__(self, bag_id: str, lock_index: Dict[str, asyncio.Lock]):
        self.lock_index = lock_index
        self.bag_id = bag_id

    async def __aenter__(self):
        self.lock = self.lock_index.get(self.bag_id)
        if self.lock is None:
            self.lock = asyncio.Lock()
            self.lock.__ref_count = 0
            self.lock_index[self.bag_id] = self.lock
        self.lock.__ref_count += 1
        await self.lock.acquire()
        return None

    async def __aexit__(self, exc_type, exc, tb):
        self.lock.release()
        self.lock.__ref_count -= 1
        if self.lock.__ref_count == 0:
            del self.lock_index[self.bag_id]
        self.lock = None


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
        self.bag_wlock = {}
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
                                                response_handler=TorrentClientError.from_response,
                                                query_delete_lru=self._nft_query_delete_lru,
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

    async def _get_nft_bag_id(self, address: str, skip_verification: bool = False, owner: str = None):
        nft_data = await self.tonlib.get_nft_data(address, skip_verification, owner=owner)
        nft_content = nft_data.individual_content

        bag_id = None
        if nft_content is not None:
            bag_id = nft_content.bag_id()
        return bag_id

    async def _nft_query_delete_lru(self, bag_id: str, peers: Dict, torrent_info: Dict):
        description = torrent_info['torrent']['description']
        if not description.startswith('nft:'):
            return 'Invalid NFT reference'
        try:
            address = prepare_address(description[4:])
        except ValueError:
            return 'Invalid NFT reference'

        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content
        nft_bag_id = nft_content.bag_id()

        if nft_bag_id != bag_id:
            return 'NFT bag_id not match'
        if nft_content.fee_due_time + self.settings.storage.confirmation_timeout * 10 < time.time():
            return 'NFT fee due time expired'
        elif len(peers['peers']) < self.settings.storage.min_redundancy:
            asyncio.create_task(self._torrent_apply_redundancy_policy(bag_id, peers))

        return None

    async def _fetch_torrent_meta(self, bag_id: str, timeout: int = None, noadd: bool = False):
        self.stats['fetch_meta'] += 1
        curr_time = st_time = time.monotonic()
        timeout = timeout or self.settings.webserver.request_timeout - 1
        if timeout < 0:
            timeout = self.settings.webserver.request_timeout

        if noadd:
            logger.warning("Fetching torrent meta, bag_id: {bag_id}, timeout: {timeout}",
                           bag_id=bag_id, timeout=timeout)
        else:
            self.stats['fetch_meta_add'] += 1
            logger.warning("Torrent missed in the local storage, adding and fetching meta, bag_id: {bag_id}, timeout: {timeout}",  # noqa: E501
                           bag_id=bag_id,  timeout=timeout)
            await self.storage.node_add(bag_id, paused=True)

        try:
            meta_ready = False
            while curr_time < st_time + timeout:
                await asyncio.sleep(1)
                try:
                    result = await self.storage.node_get(bag_id)
                    total_size = int(result['torrent']['total_size'])
                    if total_size > self.settings.storage.storage_bag_size_limit:
                        raise exceptions.TorrentSizeLimit(self.settings.storage.storage_bag_size_limit)
                    if total_size > 0:
                        meta_ready = True
                        break
                except exceptions.TorrentNotFound:
                    pass

            if not meta_ready:
                raise exceptions.TorrentMetaNotReady()
            await self.storage.node_download_resume(bag_id)
            if int(result['torrent']['files_count']) == 0:
                meta_ready = False
                while curr_time < st_time + timeout:
                    await asyncio.sleep(1)
                    try:
                        result = await self.storage.node_get(bag_id)
                        if int(result['torrent']['files_count']) > 0:
                            meta_ready = True
                            break
                    except exceptions.TorrentNotFound:
                        pass

            if not meta_ready:
                raise exceptions.TorrentMetaNotReady()
            logger.info("Torrent meta has been fetched, bag_id: {bag_id}", bag_id=bag_id)
        except (asyncio.CancelledError, Exception) as E:
            if isinstance(E, asyncio.CancelledError):
                logger.warning('Torrent meta fetch canceled, and will be removed, bag_id: {bag_id}, exc: {exc}',
                               bag_id=bag_id, exc=type(E).__name__)
            else:
                logger.warning('Torrent meta fetch failed, and will be removed, bag_id: {bag_id}, exc: {exc}',
                               bag_id=bag_id, exc=str(E))
            await self.storage.node_remove(bag_id)
            self.stats['fetch_meta_error'] += 1
            raise
        return result

    async def get_nft_torrent(self, address: str = None, bag_id: str = None, add_on_notfound: bool = True):
        bag_id = bag_id or await self._get_nft_bag_id(address)
        if bag_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        meta_ready = noadd = True
        async with BagWriteLock(bag_id, self.bag_wlock):
            try:
                result = await self.storage.node_get(bag_id)
                if result['torrent']['total_size'] == "0":
                    meta_ready = False
            except exceptions.TorrentNotFound:
                self.stats['misses'] += 1
                if not add_on_notfound:
                    raise
                meta_ready = noadd = False
            if not meta_ready:
                result = await self._fetch_torrent_meta(bag_id, noadd=noadd)

        return result

    async def _torrent_apply_redundancy_policy(self, bag_id: str, peers: Dict = None):
        if peers is None:
            try:
                peers = await self.storage.node_get_peers(bag_id)
            except exceptions.TorrentClientError as E:
                logger.error("Applying redundancy policy, failed to get peers, BAG Id: {bag_id}, exc: {exc}",
                             bag_id=bag_id, exc={str(E)})
                return False

        replica_set = set(x['adnl_id'] for x in peers['peers'])
        if len(replica_set) >= self.settings.storage.min_redundancy:
            return True

        logger.info("Apply redundancy policy to torrent, BAG Id: {bag_id}, replicas: {replicas}, min_redundancy: {min_redundancy}",  # noqa: E501
                    bag_id=bag_id, replicas=len(replica_set),
                    min_redundancy=self.settings.storage.min_redundancy)
        node_state = await self.storage.get_node_state()
        random.shuffle(node_state)

        calls_count = calls_error = 0
        async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.settings.storage.request_timeout * 2)
                ) as session:
            for node in node_state:
                host = await self._get_peer_hostname(node["ip_str"])
                calls_count += 1
                self.stats['call_replicate'] += 1
                try:
                    logger.info("Add torrent to storage peer, ADNL: {adnl}, host: {host}, BAG Id: {bag_id}",
                                adnl=node["adnl_id"], host=host, bag_id=bag_id)

                    async with await session.post(self._get_peer_uri(host, f'/api/v1/storage/torrent/{bag_id}'),
                                                  headers=self._get_peer_headers(host),
                                                  verify_ssl=self.settings.webserver.verify_ssl,
                                                  allow_redirects=False) as resp:
                        if self.settings.webserver.bearer_auth_response:
                            await self.jwt_bearer.response_credentials(resp, host)
                        if resp.status == status.HTTP_200_OK or resp.status == status.HTTP_409_CONFLICT:
                            replica_set.add(node["adnl_id"])
                        else:
                            self.stats['call_replicate_error'] += 1
                            calls_error += 1
                            logger.warning("Add torrent to storage peer error, ADNL: {adnl}, host: {host}, BAG Id: {bag_id}, status: {status}, body: {body}",  # noqa: E501
                                           adnl=node["adnl_id"], host=host, bag_id=bag_id,
                                           status=resp.status, body=await resp.read())
                except Exception as E:
                    if isinstance(E, ServerResponseAuthError):
                        self.stats['remote_auth_error'] += 1
                    self.stats['call_replicate_error'] += 1
                    calls_error += 1
                    logger.warning("Add torrent to storage peer error, ADNL: {adnl}, host: {host}, BAG Id: {bag_id}, exc: {exc}",  # noqa: E501
                                   adnl=node["adnl_id"], host=host, bag_id=bag_id, exc=str(E))
                if len(replica_set) >= self.settings.storage.min_redundancy:
                    break

        if len(replica_set) < self.settings.storage.min_redundancy:
            logger.warning("Unable to apply redundancy policy to torrent, BAG Id: {bag_id}, replicas: {replicas}, redundancy: {min_redundancy}, calls: {calls_count}, errors: {calls_error}",  # noqa: E501
                           bag_id=bag_id, replicas=len(replica_set),
                           min_redundancy=self.settings.storage.min_redundancy,
                           calls_error=calls_error, calls_count=calls_count)
        else:
            logger.warning("Redundancy policy has been applied to torrent, BAG Id: {bag_id}, replicas: {replicas}, redundancy: {min_redundancy}, calls: {calls_count}, errors: {calls_error}",  # noqa: E501
                           bag_id=bag_id, replicas=len(replica_set),
                           min_redundancy=self.settings.storage.min_redundancy,
                           calls_error=calls_error, calls_count=calls_count)

    async def _confirm_nft_torrent(self, address, old_bag_id, bag_id):
        curr_time = st_time = time.monotonic()
        nft_bag_id = None
        while st_time + self.settings.storage.confirmation_timeout > curr_time:
            await asyncio.sleep(10)
            nft_bag_id = await self._get_nft_bag_id(address)
            if nft_bag_id == bag_id:
                break
            curr_time = time.monotonic()

        async with BagWriteLock(bag_id, self.bag_wlock):
            if nft_bag_id != bag_id:
                self.stats['create_rollback'] += 1
                logger.warning("Newly created NFT Torrent removed due to confirmation timeout, NFT: {address}, bag_id: {bag_id}",  # noqa: E501
                               address=address, bag_id=bag_id)
                await self.storage.node_remove(bag_id)
                return

            self.stats['create_confirm'] += 1
            logger.warning("Newly created NFT Torrent confirmed, NFT: {address}, bag_id: {bag_id}",
                           address=address, bag_id=bag_id)
            await self.storage.node_upload_resume(bag_id)
            if bag_id is not None:
                await self.storage.node_remove(old_bag_id)

        await self._torrent_apply_redundancy_policy(bag_id)

    async def _get_peer_hostname(self, ip: str, force: bool = False):
        # hostinfo = self.peer_hostnames.get(ip)
        # if hostinfo is None or force:
        #     hostinfo = await self.resolver.gethostbyaddr(ip)
        #     self.peer_hostnames[ip] = hostinfo
        return ip.split(':')[0]

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

    async def _peer_remote_call(self, peer: Dict[str, Any], remote_path: str):
        host = await self._get_peer_hostname(peer["ip_str"])
        result = {}
        logger.info("Call storage remote peer, ADNL: {adnl}, host: {host}, remote_path: {remote_path}",
                    adnl=peer["adnl_id"], host=host, remote_path=remote_path)
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
                logger.warning("Call storage remote peer error, ADNL: {adnl}, host: {host}, remote_path: {remote_path}, exc: {exc}",  # noqa: E501
                               adnl=peer["adnl_id"], host=host, remote_path=remote_path, exc=str(E))
        return result

    async def get_storage_peer_state(self, adnl_id: str, remote_path: str):
        peers = [x for x in await self.storage.get_node_state() if x['adnl'] == adnl_id]
        if len(peers) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        peer = peers[0]

        result = {
            'remote_state': await self._peer_remote_call(peer, remote_path),
            'token': self.jwt_bearer.get_jwt_token(await self._get_peer_hostname(peer["ip_str"]))
        }
        if result['remote_state'].get('status', 0) == status.HTTP_200_OK:
            result['remote_state']['response'] = json.loads(result['remote_state']['response'])
        result.update(peer)
        return result

    async def get_nft_torrent_content(self,
                                      address: str = None,
                                      bag_id: str = None,
                                      file_path: str = None,
                                      digest: str = None) -> FileResponse:
        torrent_info = await self.get_nft_torrent(address, bag_id=bag_id)
        bag_id = bag_id or parse_bag_id(torrent_info['torrent']['hash'])

        files = None
        if file_path is not None:
            file_path = os.path.normpath(file_path)
            files = [x for x in torrent_info['files'] if x['name'] == file_path]
        if digest is not None:
            files = [x for x in torrent_info['files'] if x['digest'] == digest]

        if not files:
            raise exceptions.TorrentFileNotFound()

        if files[0]['size'] != files[0]['downloaded_size']:
            peers = await self.storage.node_get_peers(bag_id)
            good_peers = [x for x in peers['peers'] if x['ready_parts'] == peers['total_parts']]
            if good_peers:
                remote_uri = f'/api/v1/storage/torrent/{bag_id}/c/{files[0]["digest"]}'
                remote_result = await self._peer_remote_call(good_peers[0], remote_uri)
                if remote_result['status'] == status.HTTP_200_OK:
                    return StreamingResponse(io.BytesIO(remote_result['response']), headers=remote_result['headers'])

            raise exceptions.TorrentStorageError("Torrent file not ready")

        target_path = os.path.join(
            self.settings.storage.storage_db_torrent_path or
            os.path.join(self.settings.storage.storage_db_path, 'torrent/torrent-files'),
            bag_id)
        torrent_dir = os.path.join(target_path, torrent_info['torrent']['dir_name'])
        if not os.path.isdir(torrent_dir):
            # Try to fallback
            torrent_dir = os.path.join(target_path, self.settings.storage.torrent_dirname)

        target_file = os.path.join(torrent_dir, files[0]['name'])
        if not os.path.isfile(target_file):
            logger.warning("Torrent file not exists in daemon storage, bag_id: {bag_id}, file={filename}",
                           bag_id=bag_id, filename=target_file)
            raise exceptions.TorrentStorageError("Torrent file not exists in daemon storage")

        return FileResponse(target_file, headers={"Cache-Control": "public, max-age=3600"})

    async def get_default_image(self, address: str):
        headers = {"Cache-Control": "public, max-age=3600"}
        nft_collection = self.collection_config.get_collection(address)
        if nft_collection is not None:
            return FileResponse(nft_collection.image, headers=headers)

        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content

        image = nft_content.image()
        if nft_content.bag_id() and image and image[0] == ":":
            return await self.get_nft_torrent_content(address, bag_id=nft_content.bag_id(), digest=image[1:])
        if image:
            return RedirectResponse(image)
        if nft_content.image_data():
            response = StreamingResponse(io.BytesIO(nft_content.image_data()),
                                         media_type='image/webp', headers=headers)
            return response

        # TODO: Generate dynamic default image with pets Name
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    async def create_nft_torrent(self, address: str, files: List[UploadFile], owner: str = None):
        bag_id = await self._get_nft_bag_id(address, owner=owner)
        node_state = await self.storage.get_node_state()

        if len(node_state) < self.settings.storage.min_redundancy:
            raise exceptions.TorrentStorageError("Local storage node unable to comply required redundancy")
        total_size = sum([f.size for f in files])
        if total_size > self.settings.storage.storage_bag_size_limit:
            raise exceptions.TorrentSizeLimit(self.settings.storage.storage_bag_size_limit)

        torrent_info = None
        try:
            self.stats['create'] += 1
            with tempfile.TemporaryDirectory(dir=self.settings.storage.storage_temp_dir) as tmpdirname:
                target_path = os.path.join(tmpdirname, self.settings.storage.torrent_dirname)
                logger.warning("Creating new NFT Torrent, NFT: {address}, path: {target_path}, nft bag_id: {bag_id}, size={size}",  # noqa: E501
                               address=address, target_path=target_path, bag_id=bag_id, size=total_size)
                os.mkdir(target_path)
                for file in files:
                    try:
                        with open(os.path.join(target_path, file.filename), 'wb') as f:
                            shutil.copyfileobj(file.file, f)
                    finally:
                        file.file.close()

                torrent_description = f'nft:{address}'
                async with BagWriteLock(bag_id, self.bag_wlock):
                    try:
                        torrent_info = await self.storage.node_create(os.path.join(target_path),
                                                                      torrent_description, copy=True,
                                                                      check_existance=False, no_upload=True)
                    except exceptions.TorrentDuplicateHash as E:
                        self.stats['create_duplicate'] += 1
                        torrent_info = await self.storage.node_get(E.bag_id)
                        # torrent doesn't belong to our NFT
                        if torrent_info['torrent']['description'] and \
                                torrent_info['torrent']['description'] != torrent_description:
                            raise exceptions.TorrentForbidden()
                        # trying to recreate
                        if not torrent_info['torrent']['completed']:
                            self.stats['recreate'] += 1
                            await self.storage.node_remove(E.bag_id)
                            torrent_info = await self.storage.node_create(os.path.join(target_path),
                                                                          torrent_description, copy=True,
                                                                          check_existance=False, no_upload=True)

            new_bag_id = parse_bag_id(torrent_info['torrent']['hash'])
            if not torrent_info['torrent']['active_upload']:
                if bag_id != new_bag_id:
                    logger.info("Waiting for confirmation newly created NFT Torrent, NFT: {address}, new bag_id: {bag_id}",  # noqa: E501
                                address=address, bag_id=new_bag_id)
                    self.loop.create_task(self._confirm_nft_torrent(address, bag_id, new_bag_id))
                else:
                    self.stats['create_confirm'] += 1
                    logger.warning("Newly created NFT Torrent already confirmed, NFT: {address}, bag_id: {bag_id}",
                                   address=address, bag_id=bag_id)
                    await self.storage.node_upload_resume(new_bag_id)
                    torrent_info['torrent']['active_upload'] = True
                    self.loop.create_task(self._torrent_apply_redundancy_policy(new_bag_id))
        except Exception:
            self.stats['create_error'] += 1
            raise

        return torrent_info

    async def add_torrent(self, bag_id: str) -> JSONResponse:
        async with BagWriteLock(bag_id, self.bag_wlock):
            return JSONResponse(await self.storage.node_add(bag_id))

    async def remove_torrent(self, bag_id: str) -> JSONResponse:
        async with BagWriteLock(bag_id, self.bag_wlock):
            return JSONResponse(await self.storage.node_remove(bag_id))
