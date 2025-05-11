import asyncio
import aiohttp
import json
import time
import io
from mimetypes import guess_type
from collections import Counter
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse, urljoin

from loguru import logger

from pyTON.cache import CacheManager, DisabledCacheManager
from fastapi import UploadFile, status, HTTPException
from fastapi.responses import StreamingResponse, FileResponse

from NFTorrent.settings import IpfsSettings
from NFTorrent.pyTON.manager import TonlibManager
from NFTorrent import exceptions
from NFTorrent import models


SCHEME_IPFS = 'ipfs'

def parse_uri(uri: str) -> Tuple[str, str, str]:
    comp = urlparse(uri)
    cid = path = digest = None
    if comp[0] == SCHEME_IPFS:
        cid, path, digest = comp[1], comp[2], comp[5]
        if path and path[0] == '/':
            path = path[1:]
    return cid, path, digest


class CidWriteLock:

    def __init__(self, cid: str, lock_index: Dict[str, asyncio.Lock]):
        self.lock_index = lock_index
        self.cid = cid

    async def __aenter__(self):
        self.lock = self.lock_index.get(self.cid)
        if self.lock is None:
            self.lock = asyncio.Lock()
            self.lock.__ref_count = 0
            self.lock_index[self.cid] = self.lock
        self.lock.__ref_count += 1
        await self.lock.acquire()
        return None

    async def __aexit__(self, exc_type, exc, tb):
        self.lock.release()
        self.lock.__ref_count -= 1
        if self.lock.__ref_count == 0:
            del self.lock_index[self.cid]
        self.lock = None


class IpfsException(Exception):
    pass

class IpfsRpcManager:

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

        self.cid_wlock = {}
        self.tasks = {}
        self.stats: Dict[str, int] = Counter()

        # cache setup
        self.setup_cache()
        self.client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout),
            base_url=urljoin(self.settings.kubo_rpc_uri + '/', 'api/v0/')
        )

    async def shutdown(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.wait(self.tasks.values())
        self.client.close()

    def setup_cache(self):
        pass
        # self.node_list = self.cache_manager.cached(expire=15)(self.node_list)
        # self.node_get = self.cache_manager.cached(expire=600)(self.node_get)

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
        return cid

    async def cid_pin(self, cid: str = None, name: str = None):
        path = f'pin/add?arg={cid}&recursive=true'
        if name is not None:
            path += f'&name={name}'
        async with self.client.post(path) as resp:
            if resp.status != status.HTTP_200_OK:
                raise IpfsException(f'Error response: status={resp.status}, text={await resp.text()}')
            return await resp.json()

    async def cid_unpin(self, cid: str = None):
        async with self.client.post(f'pin/rm?arg={cid}&recursive=true') as resp:
            if resp.status != status.HTTP_200_OK:
                raise IpfsException(f'Error response: status={resp.status}, text={await resp.text()}')
            return await resp.json()

    async def confirm_content(self, address, old_cid, cid):
        curr_time = st_time = time.monotonic()
        curr_cid = None
        while st_time + self.settings.confirmation_timeout > curr_time:
            await asyncio.sleep(10)
            curr_cid = await self.get_nft_cid(address)
            if curr_cid == cid:
                break
            curr_time = time.monotonic()

        async with CidWriteLock(cid, self.cid_wlock):
            if curr_cid != cid:
                self.stats['create_rollback'] += 1
                logger.warning("Newly created IPFS CID removed due to confirmation timeout, NFT: {address}, cid: {cid}, curr_cid={curr_cid}",  # noqa: E501
                               address=address, cid=cid, curr_cid=curr_cid)
                await self.cid_unpin(cid)
                return

            self.stats['create_confirm'] += 1
            logger.warning("Newly created IPFS CID confirmed, NFT: {address}, cid: {cid}",
                           address=address, cid=cid)
            await self.cid_pin(cid, name=address)
            if old_cid is not None:
                await self.cid_unpin(old_cid)
        # await self.apply_redundancy_policy(bag_id)


    # High-Level API
    async def create_content(self, address: str, files: List[UploadFile], owner: str = None):
        cid = await self.get_nft_cid(address, owner=owner)

        total_size = sum([f.size for f in files])
        if total_size > self.settings.storage_cid_size_limit:
            raise exceptions.TorrentSizeLimit(self.settings.storage_cid_size_limit)

        logger.warning("Creating new IPFS CID, NFT: {address}, curr_cid: {cid}, size={size}",  # noqa: E501
                       address=address, cid=cid, size=total_size)
        self.stats['create'] += 1
        try:
            async with CidWriteLock(address, self.cid_wlock):
                data = aiohttp.FormData()
                for f in files:
                    data.add_field('files', await f.read(), filename=f.filename, content_type=f.content_type)
                data.add_field('files', address, filename='.nft')
                async with self.client.post('add?recursive=true&wrap-with-directory=true&pin=false&cid-version=1', data=data) as resp:
                    if resp.status != status.HTTP_200_OK:
                        raise IpfsException(f'Error response: status={resp.status}, text={await resp.text()}')

                    _resp = await resp.text()

                content = None
                files = []
                for line in _resp.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if item['Name'] == '':
                        content = models.NftContentInfo(hash=item['Hash'], size=item['Size'], files=[])
                    elif item['Name'] != '.nft':
                        files.append(models.NftContentFile(name=item['Name'], size=item['Size'], hash=item['Hash']))
                if content:
                    content.files = files
                    content.make_digest()
                new_cid = content.hash

                if cid != new_cid:
                    logger.info("Waiting for confirmation newly created IPFS CID, NFT: {address}, new cid: {cid}",  # noqa: E501
                                address=address, cid=new_cid)
                    self.loop.create_task(self.confirm_content(address, cid, new_cid))
                else:
                    self.stats['create_confirm'] += 1
                    logger.warning("Newly created IPFS CID already confirmed, NFT: {address}, cid: {cid}",
                                   address=address, cid=cid)
                    await self.cid_pin(cid, name=address)
                    # self.loop.create_task(self.apply_redundancy_policy(new_bag_id))
        except Exception as E:
            self.stats['create_error'] += 1
            logger.warning("Error creating IPFS CID, NFT: {address}, size={size}, {exc}",  # noqa: E501
                           address=address, size=total_size, exc=str(E))
            raise

        return content

    async def get_content(self, address: str = None, cid: str = None):
        cid = cid or await self.get_nft_cid(address, raise_error=True)
        async with self.client.post(f'ls?arg={cid}') as resp:
            if resp.status != status.HTTP_200_OK:
                raise IpfsException(f'Error response: status={resp.status}, text={await resp.text()}')

            _resp = await resp.json()
            _content = _resp['Objects'][0]
            content = models.NftContentInfo(hash=_content['Hash'],
                                            size=0,
                                            files=[
                                                models.NftContentFile(name=x['Name'],
                                                                      size=x['Size'],
                                                                      hash=x['Hash'])
                                                for x in _content['Links']
                                                if x['Name'] != '.nft'
                                            ])
            content.size = sum([x.size for x in content.files])
            content.make_digest()
            return content

    async def get_content_file(self,
                               address: str = None,
                               cid: str = None,
                               file_path: str = None,
                               digest: str = None) -> StreamingResponse:
        cid = cid or await self.get_nft_cid(address, raise_error=True)
        info = await self.get_content(address=address, cid=cid)
        item = [x for x in info.files
                if (digest and x.digest == digest) or
                    (file_path and x.name == file_path)]
        file_path = None
        if len(item) == 1:
            file_path = item[0].name
        if file_path is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        data = None
        async with self.client.post(f'cat?arg={cid}/{file_path}') as resp:
            if resp.status != status.HTTP_200_OK:
                raise IpfsException(f'Error response: status={resp.status}, text={await resp.text()}')
            data = await resp.read()
        return StreamingResponse(io.BytesIO(data),
                                 headers={"Cache-Control": "public, max-age=3600"},
                                 media_type=guess_type(file_path)[0])

