import asyncio
import aiohttp
import json
import time
import io
import traceback
import time
import datetime
from mimetypes import guess_type
from collections import Counter
from typing import Optional, Dict, List, Tuple, Type, Any
from urllib.parse import urlparse, urljoin, urlencode

from loguru import logger

from pyTON.cache import CacheManager, DisabledCacheManager
from fastapi import UploadFile, status, HTTPException
from fastapi.responses import StreamingResponse, FileResponse

from NFTorrent.settings import IpfsSettings
from NFTorrent.pyTON.manager import TonlibManager
from NFTorrent import exceptions, models
from NFTorrent.modelsbase import dict_to_influx


SCHEME_IPFS = 'ipfs'

def parse_uri(uri: str) -> Tuple[str, str, str]:
    comp = urlparse(uri)
    cid = path = digest = None
    if comp[0] == SCHEME_IPFS:
        cid, path, digest = comp[1], comp[2], comp[5]
        if path and path[0] == '/':
            path = path[1:]
    return cid, path, digest


class LockShouldWaitError(Exception):
    pass

class OperationLock:

    def __init__(self, key: str, lock_index: Dict[str, asyncio.Lock], wait: bool = True):
        self.lock_index = lock_index
        self.key = key
        self.wait = wait

    async def __aenter__(self):
        self.lock = self.lock_index.get(self.key)
        if self.lock is None:
            self.lock = asyncio.Lock()
            self.lock.__ref_count = 0
            self.lock_index[self.key] = self.lock
        else:
            if not self.wait and self.lock.locked():
                raise LockShouldWaitError
        self.lock.__ref_count += 1
        await self.lock.acquire()
        return None

    async def __aexit__(self, exc_type, exc, tb):
        self.lock.release()
        self.lock.__ref_count -= 1
        if self.lock.__ref_count == 0:
            del self.lock_index[self.key]
        self.lock = None


class IpfsRpcHttpException(HTTPException):

    def __str__(self):
        return f'status={self.status_code}, detail={self.detail}'

class IpfsRpcManager:
    node_state_cache_timeout = 30

    def __init__(self,
                 settings: IpfsSettings,
                #  num_workers: int = None,
                #  restart_timeout: int = None,
                 cache_manager: Optional[CacheManager] = None,
                 loop: Optional[asyncio.BaseEventLoop] = None,
                 tonlib: TonlibManager = None,
                 ):
        self.settings = settings
        self.cache_manager = cache_manager or DisabledCacheManager()
        self.tonlib = tonlib
        self.loop = loop
        self.node_state = None

        self.cid_wlock = {}
        self.tasks = {
            'check_ipfs_alive': self.loop.create_task(self.check_ipfs_alive()),
        }
        self.stats: Dict[str, int] = Counter()

        # cache setup
        self.setup_cache()
        self.client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout),
            base_url=urljoin(self.settings.kubo_rpc_uri + '/', 'api/v0/')
        )
        self.cluster = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout),
            base_url=self.settings.cluster_rpc_uri
        )

    async def shutdown(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.wait(self.tasks.values())
        self.client.close()
        self.cluster.close()

    def setup_cache(self):
        pass
        # self.node_list = self.cache_manager.cached(expire=15)(self.node_list)
        # self.node_get = self.cache_manager.cached(expire=600)(self.node_get)

    async def check_ipfs_alive(self):
        logger.warning("IpfsRpcManager[check_ipfs_alive]: entering main loop")
        while True:
            try:
                try:
                    await self.get_node_state()
                except Exception as E:
                    logger.warning("IpfsRpcManager[check_ipfs_alive]: failed to get node state, exc: {excname}: {exc}",
                                   excname=type(E), exc=str(E))

                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("IpfsRpcManager[check_ipfs_alive]: Task was cancelled")
                return
            except (Exception, BaseException):
                logger.critical("IpfsRpcManager[check_ipfs_alive]: Task terminated with exception: {exc}",
                                exc=traceback.format_exc())
                await asyncio.sleep(30)

    async def get_nft_cid(self, address: str, skip_verification: bool = False, owner: str = None, raise_error: bool = False):
        nft_data = await self.tonlib.get_nft_data(address, skip_verification, owner=owner)
        nft_content = nft_data.individual_content

        cid = None
        if nft_content is not None:
            image = nft_content.image()
            if image:
                cid, _, _ = parse_uri(image)
        if raise_error and not cid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return cid, nft_content

    async def call_rpc_method(self, stat_name: str, method: Type[aiohttp.ClientResponse], uri: str, json: bool = False, text: bool = False, data: Any = None):
        kwargs = {}
        if data is not None:
            kwargs['data'] = data
        try:
            self.stats[stat_name] += 1
            logger.info("IPFS RPC Call, method: {method}, uri: {uri}", method=method.__name__, uri=uri)
            async with method(uri, **kwargs) as resp:
                if resp.status != status.HTTP_200_OK:
                    raise IpfsRpcHttpException(status_code=resp.status, detail=await resp.text())
                if json:
                    return await resp.json()
                elif text:
                    return await resp.text()
                else:
                    return await resp.read()
        except (aiohttp.client_exceptions.ClientError, aiohttp.client_exceptions.ClientConnectorError) as E:
            self.stats[f'{stat_name}_error'] += 1
            logger.error("IPFS RPC call error, method: {method}, uri: {uri}, {exc}",
                         method=method.__name__, uri=uri, exc=str(E))
            raise

    async def cid_add_local(self, files: List[UploadFile] = None) -> models.NftContentInfo:
        data = aiohttp.FormData()
        for f in files:
            data.add_field('files', await f.read(), filename=f.filename, content_type=f.content_type)
        uri = 'add?recursive=true&wrap-with-directory=true&pin=false&cid-version=1'
        response = await self.call_rpc_method('cid_add', self.client.post, uri, data=data, text=True)
        content = None
        files = []
        for line in response.split('\n'):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item['Name'] == '':
                content = models.NftContentInfo(hash=item['Hash'], size=item['Size'], files=[])
            else:
                files.append(models.NftContentFile(name=item['Name'], size=item['Size'], hash=item['Hash']))
        if content:
            content.files = files
            content.make_digest()
        return content

    async def cid_pin(self, cid: str = None, name: str = None, expire_at: float = None, address: str = None):
        name = name or ""
        if self.settings.cluster_rpc_uri:
            expire_at_str = datetime.datetime.fromtimestamp(expire_at).isoformat()+"Z" if expire_at else ""
            query_params = {
                'mode': 'recursive',
                'replication-min': self.settings.min_redundancy,
                'replication-max': self.settings.min_redundancy+2,
            }
            if name:
                query_params['name'] = name
            if expire_at:
                query_params['expire-at'] = expire_at_str
                query_params['meta-expires'] = expire_at
            if address:
                query_params['meta-nft'] = address
            uri = f'/pins/{cid}?{urlencode(query_params)}'
            return await self.call_rpc_method('pin', self.cluster.post, uri, json=True)
        else:
            uri = f'pin/add?arg={cid}&recursive=true&name={name}'
            return await self.call_rpc_method('pin', self.cluster.post, uri, json=True)

    async def cid_unpin(self, cid: str = None):
        try:
            if self.settings.cluster_rpc_uri:
                uri = f'/pins/{cid}'
                return await self.call_rpc_method('unpin', self.cluster.delete, uri, json=True)
            else:
                uri = f'pin/rm?arg={cid}&recursive=true'
                return await self.call_rpc_method('unpin', self.cluster.post, uri, json=True)
        except IpfsRpcHttpException as E:
            if E.status_code != status.HTTP_404_NOT_FOUND:
                raise

    async def cid_pin_status(self, cid: str = None):
        try:
            if self.settings.cluster_rpc_uri:
                uri = f'/pins/{cid}'
                return await self.call_rpc_method('pin_status', self.cluster.get, uri, json=True)
            else:
                uri = f'pin/ls?arg={cid}'
                return await self.call_rpc_method('pin_status', self.cluster.post, uri, json=True)
        except IpfsRpcHttpException as E:
            if E.status_code != status.HTTP_404_NOT_FOUND:
                raise

    async def confirm_content(self, address, old_cid, cid):
        async with OperationLock(f'nft:{address}:pin', self.cid_wlock, wait=False):
            curr_time = st_time = time.monotonic()
            curr_cid = None
            while st_time + self.settings.confirmation_timeout > curr_time:
                curr_cid, nft_content = await self.get_nft_cid(address)
                if curr_cid == cid:
                    break
                await asyncio.sleep(10)
                curr_time = time.monotonic()

            async with OperationLock(f'cid:{cid}:pin', self.cid_wlock):
                if curr_cid != cid:
                    self.stats['confirm_timeout'] += 1
                    logger.warning("IPFS CID was not pinned due to confirmation timeout, NFT: {address}, cid: {cid}, curr_cid={curr_cid}",  # noqa: E501
                                address=address, cid=cid, curr_cid=curr_cid)
                    # await self.cid_unpin(cid)
                    return

                logger.warning("IPFS CID pin confirmed, NFT: {address}, cid: {cid}",
                            address=address, cid=cid)
                await self.cid_pin(cid, name=address, address=address, expire_at=nft_content.storage_due_time())
                if old_cid is not None:
                    await self.cid_unpin(old_cid)

    def get_cached_node_state(self):
        return self.node_state

    async def get_node_state(self):
        curr_time = time.monotonic()
        if self.node_state is None or curr_time > self.node_state_time + self.node_state_cache_timeout:
            tasks = await asyncio.gather(
                self.call_rpc_method('repo_stat', self.client.post, 'repo/stat', json=True),
                self.call_rpc_method('swarm_peers', self.client.post, 'swarm/peers', json=True),
                self.call_rpc_method('metrics_ping', self.cluster.get, 'monitor/metrics/ping', json=True)
            )
            self.node_state_time = curr_time
            self.node_state = {
                'storage': tasks[0],
                'peers': len(tasks[1]['Peers']),
                'cluster_peers': tasks[2],
                'stats': self.stats,
            }
        return self.node_state

    def get_measurements(self, timestamp: int) -> List[str]:
        state = self.get_cached_node_state()
        if state is not None:
            _ipfs = {
                'peers': state['peers'],
                'cluster_peers': len(state['cluster_peers']),
                'cluster_active_peers': len([x for x in state['cluster_peers'] if x['valid']]),
                'size': state['storage']['RepoSize'],
                'max_size': state['storage']['StorageMax'],
                'objects': state['storage'].get('NumObjects'),
            }
        else:
            _ipfs = {}
        _ipfs.update(state["stats"])
        return [f'NFTorrentIpfs {dict_to_influx(_ipfs)} {timestamp}']

    async def get_cid_file(self,
                           uri: str = None,
                           cid: str = None,
                           file_path: str = None,
                           digest: str = None):
        if uri:
            cid, _file_path, _digest = parse_uri(uri)
            if file_path is None and digest is None:
                file_path, digest = _file_path, _digest
        if not cid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='CID not defined')
        info = await self.get_content(cid=cid)
        if len(info.files) > 0:
            if digest or file_path:
                item = [x for x in info.files
                        if (digest and x.digest == digest) or
                            (file_path and x.name == file_path)]
            else:
                item = [x for x in info.files if not x.name.startswith('.')][:1]
            if len(item) == 1:
                file_path = item[0].name
            if not file_path:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        if file_path is None:
            data = await self.call_rpc_method('cid_cat', self.client.post, f'cat?arg={cid}')
        else:
            data = await self.call_rpc_method('cid_cat', self.client.post, f'cat?arg={cid}/{file_path}')
        return data, file_path

    # High-Level API
    async def new_nft_create_content(self, owner: str, files: List[UploadFile]):
        total_size = sum([f.size for f in files])
        if total_size > self.settings.storage_cid_size_limit:
            raise exceptions.TorrentSizeLimit(self.settings.storage_cid_size_limit)
        logger.warning("Creating new IPFS CID for new NFT, owner: {owner}, size={size}",  # noqa: E501
                       address=owner, size=total_size)
        self.stats['create'] += 1
        content = None
        try:
            async with OperationLock(f'owner:{owner}:new', self.cid_wlock, wait=False):
                content = await self.cid_add_local(address=owner, files=files)
        except Exception as E:
            self.stats['create_error'] += 1
            logger.warning("Error creating IPFS CID, for new NFT, owner: {owner}, size={size}, {exc}",  # noqa: E501
                           owner=owner, size=total_size, exc=str(E))
            raise
        return content

    async def create_content(self, address: str, files: List[UploadFile], owner: str = None):
        cid, nft_content = await self.get_nft_cid(address, owner=owner)

        total_size = sum([f.size for f in files])
        if total_size > self.settings.storage_cid_size_limit:
            raise exceptions.TorrentSizeLimit(self.settings.storage_cid_size_limit)

        node_state = await self.get_cached_node_state()
        cluster_peers = len(node_state['cluster_peers'])
        if cluster_peers < self.settings.min_redundancy:
            raise exceptions.TorrentStorageError(f'Unable to comply required redundancy, min={self.settings.min_redundancy}, peers={cluster_peers}')

        logger.warning("Creating new IPFS CID, NFT: {address}, curr_cid: {cid}, size={size}",  # noqa: E501
                       address=address, cid=cid, size=total_size)
        self.stats['create'] += 1
        try:
            async with OperationLock(f'nft:{address}:add', self.cid_wlock, wait=False):
                content = await self.cid_add_local(address=address, files=files)
                new_cid = content.hash

                if cid != new_cid:
                    logger.info("Waiting for confirmation newly created IPFS CID, NFT: {address}, new cid: {cid}",  # noqa: E501
                                address=address, cid=new_cid)
                    self.loop.create_task(self.confirm_content(address, cid, new_cid))
                else:
                    self.stats['create_confirm'] += 1
                    logger.warning("Newly created IPFS CID already confirmed, NFT: {address}, cid: {cid}",
                                   address=address, cid=new_cid)
                    await self.cid_pin(new_cid, name=address, expire_at=nft_content.storage_due_time())
        except Exception as E:
            self.stats['create_error'] += 1
            logger.warning("Error creating IPFS CID, NFT: {address}, size={size}, {exc}",  # noqa: E501
                           address=address, size=total_size, exc=str(E))
            raise

        return content

    async def get_content(self, address: str = None, cid: str = None, with_pin: bool = False):
        content = None
        if not cid:
            cid, _ = await self.get_nft_cid(address, raise_error=True)
        _resp = await self.call_rpc_method('cid_ls', self.client.post, f'ls?arg={cid}', json=True)
        pin_info = None
        if with_pin:
            _pin = await self.cid_pin_status(cid)
            if _pin['metadata'] and _pin['metadata']['nft']:
                pin_info = models.NftContentPin(redundancy=len(_pin['allocations']),
                                                expires=float(_pin['metadata'].get('expires', '0')),
                                                created=time.mktime(time.strptime(_pin['created'], "%Y-%m-%dT%H:%M:%SZ")))

        _content = _resp['Objects'][0]
        content = models.NftContentInfo(hash=_content['Hash'],
                                        size=0,
                                        files=[
                                            models.NftContentFile(name=x['Name'],
                                                                    size=x['Size'],
                                                                    hash=x['Hash'])
                                            for x in _content['Links']
                                        ],
                                        pin=pin_info)
        content.size = sum([x.size for x in content.files])
        content.make_digest()
        return content

    async def get_content_file(self,
                               address: str = None,
                               uri: str = None,
                               cid: str = None,
                               file_path: str = None,
                               digest: str = None) -> StreamingResponse:
        if not uri and not cid:
            cid = (await self.get_nft_cid(address, raise_error=True))[0]
        data, file_path = await self.get_cid_file(uri=uri, cid=cid, file_path=file_path, digest=digest)
        return StreamingResponse(io.BytesIO(data),
                                 headers={"Cache-Control": "public, max-age=3600"},
                                 media_type=(guess_type(file_path)[0] if file_path else None) or 'image/webp')
