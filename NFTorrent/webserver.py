import asyncio
import aiohttp
import time
import random
import os
import shutil
import tempfile

from typing import Dict, List
from loguru import logger

from fastapi.exceptions import HTTPException
from fastapi import status
from fastapi import UploadFile

from pytonlib.utils.address import prepare_address

from pyTON.cache import CacheManager, RedisCacheManager, DisabledCacheManager
from pyTON.settings import RedisCacheSettings

from NFTorrent.pyTON.manager import TonlibManager, NftCollection
from NFTorrent.settings import Settings
from NFTorrent import exceptions, messages
from NFTorrent.manager import TonStorageCliManager
from NFTorrent.exceptions import TorrentClientError
from NFTorrent.auth import NodeJWTBearer
from NFTorrent.address import parse_bag_id

class Server:

    def __init__(self, loop: asyncio.AbstractEventLoop = None, settings: Settings = None):
        self.settings = settings or Settings.from_environment()
        self.tonlib: TonlibManager = None
        self.storage: TonStorageCliManager = None
        self.peer_hostnames = {}
        # self.resolver: aiodns.DNSResolver = None
        self.loop = loop or asyncio.get_event_loop()
        self.jwt_bearer = NodeJWTBearer(subject=self.settings.storage.storage_public_addr,
                           jwt_secret=self.settings.webserver.jwt_secret,
                           jwt_algorithm=self.settings.webserver.jwt_algorithm,
                           node_state=self.get_node_state,
                           real_ip_header=self.settings.webserver.real_ip_header)
    
    def get_node_state(self):
        return self.storage.get_cached_node_state()

    async def startup(self):
        logger.warning('Server startup initiated...')
        logger.warning('Storage public address: {addr}, HTTP API Root: {api_root}', 
                    addr=self.settings.storage.storage_public_addr, 
                    api_root=self.settings.webserver.api_root_path)        

        # self.resolver = aiodns.DNSResolver(loop=self.loop)

        cache_manager = None
        if self.settings.cache.enabled:
            if isinstance(self.settings.pyton.cache, RedisCacheSettings):
                cache_manager = RedisCacheManager(self.settings.cache)
                print(self.settings.cache)
            else:
                raise RuntimeError('Only Redis cache supported')
        else:
            cache_manager = DisabledCacheManager()

        if self.settings.tonlib.liteserver_config_path:
            self.tonlib = TonlibManager(tonlib_settings=self.settings.tonlib,
                                dispatcher=None,
                                cache_manager=cache_manager,
                                loop=self.loop,
                                nft_collections=[
                                    NftCollection(
                                        'EQDZvNPzp8kfHUBbvQRovtHOquSy6ZN_p-toP_ed35gyH1vL', 
                                        messages.PetMemoryNftContent
                                        )])
        else:
            logger.warning("Tonlib disabled, liteserver_config required")

        if self.settings.storage.num_workers:    
            self.storage = TonStorageCliManager(self.settings.storage,
                                        dispatcher=None,
                                        cache_manager=cache_manager,
                                        response_handler=TorrentClientError.from_response,
                                        query_delete_lru=self._nft_query_delete_lru,
                                        loop=self.loop)
        else:
            logger.warning("Storage disabled, num_workers required")

        await asyncio.sleep(3) # wait for manager to spawn all workers and report their status

    async def shutdown(self):
        logger.warning('Server shutdown initiated...')
        await asyncio.wait([
            self.tonlib.shutdown(),
            self.storage.shutdown(),
        ], return_when=asyncio.ALL_COMPLETED)

    async def _get_nft_bag_id(self, address: str, skip_verification: bool = False):
        nft_data = await self.tonlib.get_nft_data(address, skip_verification)
        nft_content = nft_data['individual_content']

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
        nft_content = nft_data['individual_content']
        nft_bag_id = nft_content.bag_id()

        if nft_bag_id != bag_id:
            return 'NFT bag_id not match'
        if nft_content.fee_due_time + self.settings.storage.confirmation_timeout * 10 < time.time():
            return 'NFT fee due time expired'
        elif len(peers['peers']) < self.settings.storage.min_redundancy:
            asyncio.create_task(self._torrent_apply_redundancy_policy(bag_id, peers))

        return None

    async def _get_nft_torrent(self, address, add_on_notfound: bool = True):
        bag_id = await self._get_nft_bag_id(address)
        if bag_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)    
        
        try:
            result = await self.storage.node_get(bag_id)
        except exceptions.TorrentNotFound:
            if not add_on_notfound:
                raise
            await self.storage.node_add(bag_id)
            await asyncio.sleep(1)
            result = await self.storage.node_get(bag_id)
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
        
        logger.info("Apply redundancy policy to torrent, BAG Id: {bag_id}, replicas: {replicas}, min_redundancy: {min_redundancy}", 
                    bag_id=bag_id, replicas=len(replica_set), min_redundancy=self.settings.storage.min_redundancy) 
        node_state = await self.storage.get_node_state()
        random.shuffle(node_state)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.settings.storage.request_timeout * 2)) as session:
            for node in node_state:
                host = await self._get_peer_hostname(node["ip_str"].split(':')[0])
                try:
                    logger.info("Add torrent to storage peer, ADNL: {adnl}, host: {host}, BAG Id: {bag_id}", 
                                adnl=node["adnl_id"], host=host, bag_id=bag_id)
                    

                    async with await session.post(self._get_peer_uri(host, f'/storage/torrent/{bag_id}'), 
                                            headers=self._get_peer_headers(host), 
                                            verify_ssl=self.settings.webserver.verify_ssl,
                                            allow_redirects=False) as resp:
                        if resp.status == status.HTTP_200_OK:
                            replica_set.add(node["adnl_id"])
                except Exception as E: 
                    logger.warning("Add torrent to storage peer error, ADNL: {adnl}, host: {host}, BAG Id: {bag_id}, exc: {exc}", 
                                adnl=node["adnl_id"], host=host, bag_id=bag_id, exc=str(E))
                if len(replica_set) >= self.settings.storage.min_redundancy:
                    break

        if len(replica_set) < self.settings.storage.min_redundancy:
            logger.warning("Unable to apply redundancy policy to torrent, BAG Id: {bag_id}, replicas: {replicas}, min_redundancy: {min_redundancy}", 
                    bag_id=bag_id, replicas=len(replica_set), min_redundancy=self.settings.storage.min_redundancy)         

    async def _confirm_nft_torrent(self, address, old_bag_id, bag_id):        
        curr_time = st_time = time.monotonic()
        nft_bag_id = None
        while st_time + self.settings.storage.confirmation_timeout > curr_time:
            await asyncio.sleep(10)
            nft_bag_id = await self._get_nft_bag_id(address)
            if nft_bag_id == bag_id:
                break
            curr_time = time.monotonic()
        
        if nft_bag_id != bag_id:
            logger.warning("Newly created NFT Torrent removed due to confirmation timeout, NFT: {address}, bag_id: {bag_id}", 
                           address=address, bag_id=bag_id)        
            await self.storage.node_remove(bag_id)
            return
        
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
        return ip

    def _get_peer_uri(self, host: str, path: str):
        authority = f'{host}:{self.settings.webserver.port}' if self.settings.webserver.port else host
        if self.settings.webserver.api_root_path[-1] == '/' and path[0] == '/':
            path = self.settings.webserver.api_root_path + path[1:]
        elif self.settings.webserver.api_root_path[-1] != '/' and path[0] != '/':
            path = self.settings.webserver.api_root_path + '/' + path
        else:
            path = self.settings.webserver.api_root_path + path        
        schema = 'https' if self.settings.webserver.enable_ssl else 'http'
        return f'{schema}://{authority}{path}'

    def _get_peer_headers(self, host: str):
        return {
            'Authorization': 'Bearer ' + self.jwt_bearer.get_jwt_token(host)
        }
    
    # API
    async def get_healthcheck(self):
        tonlib_state = sum([1 for x in self.tonlib.get_workers_state().values() if x['is_working']])
        stotage_state = sum([1 for x in self.storage.get_workers_state() if x['is_healthy']])

        return {
            'tonlib': bool(tonlib_state),
            'storage': bool(stotage_state),
        }
    
    async def get_storage_peer_state(self, adnl_id: str, remote_path: str):
        peer = [x for x in await self.storage.get_node_state() if x['adnl'] == adnl_id]
        if len(peer) == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        
        state = {}
        host = await self._get_peer_hostname(peer[0]["ip_str"].split(':')[0])
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.settings.storage.request_timeout * 2)) as session:
            try:
                async with await session.get(self._get_peer_uri(host, remote_path), 
                                            headers=self._get_peer_headers(host), 
                                            verify_ssl=self.settings.webserver.verify_ssl,
                                            allow_redirects=False) as resp:
                    state['status'] = resp.status
                    state['response'] = await resp.json()
            except Exception as E: 
                print(E.__dict__)
                state['error'] = str(E)
                logger.warning("Call storage peer error, ADNL: {adnl}, host: {host}, exc: {exc}", 
                                adnl=peer[0]["adnl_id"], host=host, exc=str(E))

        result = {
            'remote_state': state,
        }
        result.update(peer[0])
        return result    
    
    async def get_nft_torrent_filename(self, address: str, file_path: str) -> str:
        torrent_info = await self._get_nft_torrent(address)
        if not torrent_info['torrent']['completed'] and int(torrent_info['torrent']['files_count']) == 0:
            raise exceptions.TorrentStorageError("Torrent meta not ready")
        file_path = os.path.normpath(file_path)

        files = [x for x in torrent_info['files'] if x['name'] == file_path]
        if not files:
            raise exceptions.TorrentPathNotFound()
        
        if files[0]['size'] != files[0]['downloaded_size']:
            # TODO: Trru to locate peer with ready parts and proxy request
            raise exceptions.TorrentStorageError("Torrent file not ready")
        
        target_file = os.path.join(
            self.settings.storage.storage_db_torrent_path or os.path.join(self.settings.storage.storage_db_path, 'torrent/torrent-files'), 
            parse_bag_id(torrent_info['torrent']['hash']),
            self.settings.storage.torrent_dirname,
            files[0]['name'])
        if not os.path.isfile(target_file):
            raise exceptions.TorrentStorageError("Torrent file not exists in daemon storage")
        
        return target_file
    
    async def create_nft_torrent(self, address: str, files: List[UploadFile]):
        bag_id = await self._get_nft_bag_id(address)
        node_state = await self.storage.get_node_state()

        if len(node_state) < self.settings.storage.min_redundancy - 1:
            raise exceptions.TorrentStorageError("Local storage node unable to comply required redundancy")

        torrent_info = None
        with tempfile.TemporaryDirectory() as tmpdirname:
            target_path = os.path.join(tmpdirname, self.settings.storage.torrent_dirname)
            logger.warning("Creating new NFT Torrent, NFT: {address}, path: {target_path}, bag_id: {bag_id}", 
                           address=address, target_path=target_path, bag_id=bag_id)
            os.mkdir(target_path)
            for file in files:
                try:            
                    with open(os.path.join(target_path, file.filename), 'wb') as f:
                        shutil.copyfileobj(file.file, f)            
                finally:
                    file.file.close()
            
            torrent_description = f'nft:{address}'
            try:
                torrent_info = await self.storage.node_create(os.path.join(target_path, ''), 
                                                        torrent_description, copy=True, 
                                                        check_existance=False, 
                                                        no_upload=True)
            except exceptions.TorrentDuplicateHash as E:            
                torrent_info = await self.storage.node_get(E.bag_id)
                # torrent doesn't belong to our NFT
                if torrent_info['torrent']['description'] and torrent_info['torrent']['description'] != torrent_description:
                    raise exceptions.TorrentForbidden()            
                # trying to recreate
                if not torrent_info['torrent']['completed']:                
                    await self.storage.node_remove(E.bag_id)
                    torrent_info = await self.storage.node_create(os.path.join(target_path, ''), 
                                                            torrent_description, copy=True, 
                                                            check_existance=False, 
                                                            no_upload=True)
        
        new_bag_id = parse_bag_id(torrent_info['torrent']['hash'])
        if not torrent_info['torrent']['active_upload']:
            if bag_id != new_bag_id:
                logger.info("Waiting for confirmation newly created NFT Torrent, NFT: {address}, new bag_id: {bag_id}", 
                            address=address, bag_id=new_bag_id)
                self.loop.create_task(self._confirm_nft_torrent(address, bag_id, new_bag_id))
            else:
                logger.warning("Newly created NFT Torrent already confirmed, NFT: {address}, bag_id: {bag_id}", 
                            address=address, bag_id=bag_id)            
                await self.storage.node_upload_resume(new_bag_id)
                torrent_info['torrent']['active_upload'] = True
                self.loop.create_task(self._torrent_apply_redundancy_policy(new_bag_id))

        return torrent_info        
