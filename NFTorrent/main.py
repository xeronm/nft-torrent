import asyncio
import sys
import os
import tempfile
import shutil
import time
import random
import aiohttp
from fastapi import FastAPI
from typing import Annotated
from functools import wraps

from fastapi.exceptions import HTTPException, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi import status, UploadFile
from fastapi.params import Depends

from pytonlib import TonlibException

from pyTON.settings import RedisCacheSettings
from pyTON.cache import CacheManager, RedisCacheManager, DisabledCacheManager

from NFTorrent.pyTON.manager import TonlibManager, NftCollection
from NFTorrent import __meta__
from NFTorrent.settings import Settings
from NFTorrent import models, exceptions, messages
from NFTorrent.manager import TonStorageCliManager
from NFTorrent.storage import parse_bag_id


from loguru import logger

settings = Settings.from_environment()

tags_metadata = [
]

app = FastAPI(
    title=__meta__.__title__,
    description=__meta__.__description__,
    version=__meta__.__version__,
    docs_url='/',
    responses={
        422: {'description': 'Validation Error'},
        504: {'description': 'Lite Server Timeout'}
    },
    root_path=settings.webserver.api_root_path,
    openapi_tags=tags_metadata
)

tonlib = None
storage = None

@app.on_event("startup")
async def startup():
    logger.remove()
    logger.add(sys.stdout, level=settings.logging.level, enqueue=True, serialize=settings.logging.jsonify)
    logger.warning('Server startup initiated...')

    # setup tonlib multiclient
    global tonlib
    global storage

    loop = asyncio.get_event_loop()

    cache_manager = None
    if settings.cache.enabled:
        if isinstance(settings.pyton.cache, RedisCacheSettings):
            cache_manager = RedisCacheManager(settings.cache)
            print(settings.cache)
        else:
            raise RuntimeError('Only Redis cache supported')
    else:
        cache_manager = DisabledCacheManager()

    if settings.tonlib.liteserver_config_path:
        tonlib = TonlibManager(tonlib_settings=settings.tonlib,
                            dispatcher=None,
                            cache_manager=cache_manager,
                            loop=loop,
                            nft_collections=[
                                NftCollection('EQDZvNPzp8kfHUBbvQRovtHOquSy6ZN_p-toP_ed35gyH1vL', messages.PetMemoryNftContent)
                            ])
    else:
        logger.warning("Tonlib disabled, liteserver_config required")

    if settings.storage.num_workers:    
        storage = TonStorageCliManager(settings.storage,
                                        dispatcher=None,
                                        cache_manager=cache_manager,
                                        loop=loop)
    else:
        logger.warning("Storage disabled, num_workers required")

    await asyncio.sleep(2) # wait for manager to spawn all workers and report their status

@app.on_event("shutdown")
async def shutdown_event():
    logger.warning('Server shutdown initiated...')
    await asyncio.wait([
        tonlib.shutdown(),
        storage.shutdown(),
    ], return_when=asyncio.ALL_COMPLETED)


# Exception handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc.detail), status=exc.status_code)
    return JSONResponse(res.dict(exclude_none=True), status_code=res.status)


@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc):
    res = models.ProblemDetail(
        title=type(exc).__name__, 
        detail='Request validation failed, see errors for details', 
        errors=[{k: v for k, v in err.items() if k != 'ctx'} for err in exc.errors()], 
        status=status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(asyncio.TimeoutError)
async def timeout_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_504_GATEWAY_TIMEOUT)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_504_GATEWAY_TIMEOUT)


@app.exception_handler(TonlibException)
async def tonlib_error_result_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.exception_handler(Exception)
async def fastapi_generic_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def wrap_result(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = await asyncio.wait_for(func(*args, **kwargs), settings.tonlib.request_timeout)
        return result
    return wrapper

# API
@app.get('/healthcheck', include_in_schema=False)
async def healthcheck():
    tonlib_state = sum([1 for x in tonlib.get_workers_state() if x['is_working']])
    stotage_state = sum([1 for x in storage.get_workers_state() if x['is_healthy']])

    return {
        'tonlib': bool(tonlib_state),
        'storage': bool(stotage_state)
    }


@app.get('/tonlib/state', include_in_schema=False)
@wrap_result
async def get_tonlib_worker_state():
    return tonlib.get_workers_state()


@app.get('/storage/state', include_in_schema=False)
@wrap_result
async def get_storage_worker_state():
    return storage.get_workers_state()


@app.get('/storage/peers', include_in_schema=False)
@wrap_result
async def get_storage_peers():
    return await storage.get_node_state()


@app.get('/storage/torrent/{bag_id}', response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def add_torrent(request: models.TorrentMethod = Depends()):
    """
    Get Torrent information.
    """
    result = await storage.node_get(request.bag_id)
    if result.get('error', None) == 'Query error: No such torrent':
        raise exceptions.TorrentNotFound()
    if 'error' in result:
        raise exceptions.TorrentClientError(result)
    return result


@app.post('/storage/torrent/{bag_id}', response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def add_torrent(request: models.TorrentMethod = Depends()):
    """
    Add Torrent.
    """
    # TODO Validate adnl_id and ip_str
    result = await storage.node_add(request.bag_id)
    if 'error' in result:
        raise exceptions.TorrentClientError(result)
    return result


@app.get('/nft/{address}', response_model_exclude_none=True, tags=['nft'])
@wrap_result
async def get_nft_data(request: models.NftMethod = Depends()):
    """
    Get NFT Data information.
    """
    return await tonlib.get_nft_data(request.address)


@app.get('/nft/{address}/torrent', response_model_exclude_none=True, tags=['nft-torrent'])
@wrap_result
async def get_nft_torrent(request: models.NftMethod = Depends()):
    """
    Get NFT Torrent information.
    """
    return await _get_nft_torrent(request.address)


@app.get('/nft/{address}/torrent/{file_path:path}', response_model_exclude_none=True, tags=['nft-torrent'])
@wrap_result
async def get_nft_torrent_file(request: models.NftTorrentMethod = Depends()):
    """
    Get NFT Torrent File.
    """
    torrent_info = await _get_nft_torrent(request.address)
    file_path = os.path.normpath(request.file_path)

    files = [x for x in torrent_info['files'] if x['name'] == file_path]
    if not files:
        raise exceptions.TorrentPathNotFound()
    
    if files[0]['size'] != files[0]['downloaded_size']:
        raise exceptions.TorrentStorageError("Specified file not ready")
    
    target_file = os.path.join(
        settings.storage.storage_db_torrent_path or os.path.join(settings.storage.storage_db_path, 'torrent/torrent-files'), 
        parse_bag_id(torrent_info['torrent']['hash']),
        settings.storage.torrent_dirname,
        files[0]['name'])
    if not os.path.isfile(target_file):
        raise exceptions.TorrentStorageError("File not exists in daemon storage")
    
    return FileResponse(path=target_file)


@app.post('/nft/{address}/torrent', response_model_exclude_none=True, tags=['nft-torrent'])
async def create_nft_torrent(request: models.NftTorrentCreate = Depends()):
    """
    Create NFT Torrent.
    """    
    bag_id = await _get_nft_bag_id(request.address)

    node_state = await storage.get_node_state()
    print(node_state)
    if len(node_state) < settings.storage.min_redundancy - 1:
        raise exceptions.TorrentStorageError("Local storage node unable to comply required redundancy")

    torrent_info = None
    with tempfile.TemporaryDirectory() as tmpdirname:
        target_path = os.path.join(tmpdirname, settings.storage.torrent_dirname)
        logger.warning("Creating new NFT Torrent, NFT: {address}, path: {target_path}, bag_id: {bag_id}", address=request.address, target_path=target_path, bag_id=bag_id)
        os.mkdir(target_path)
        for file in request.files:
            try:            
                with open(os.path.join(target_path, file.filename), 'wb') as f:
                    shutil.copyfileobj(file.file, f)            
            finally:
                file.file.close()
        
        torrent_description = f'nft:{request.address}'
        torrent_info = await storage.node_create(os.path.join(target_path, ''), torrent_description, copy=True, check_existance=False, no_upload=True)
        duplicate_hash_prefix = "Query error: Cannot add torrent: duplicate hash "
        if 'error' in torrent_info and torrent_info['error'].startswith(duplicate_hash_prefix):            
            torrent_info = await storage.node_get(parse_bag_id(torrent_info['error'][len(duplicate_hash_prefix):]))
            if torrent_info['torrent']['description'] != torrent_description:
                raise exceptions.TorrentForbidden()

    if 'error' in torrent_info:
        raise exceptions.TorrentClientError(torrent_info)
    
    new_bag_id = parse_bag_id(torrent_info['torrent']['hash'])
    if not torrent_info['torrent']['active_upload']:
        if bag_id != new_bag_id:
            logger.info("Waiting for confirmation newly created NFT Torrent, NFT: {address}, new bag_id: {bag_id}", address=request.address, bag_id=new_bag_id)
            asyncio.create_task(_confirm_nft_torrent(request.address, new_bag_id, timeout=settings.storage.confirmation_timeout))
        else:
            result = await storage.node_upload_resume(new_bag_id)
            asyncio.create_task(_torrent_apply_redundancy_policy(bag_id))
            if 'error' not in result:
                torrent_info['torrent']['active_upload'] = True

    return torrent_info


# Internal methods
async def _get_nft_bag_id(address: str, skip_verification: bool = False):
    nft_data = await tonlib.get_nft_data(address, skip_verification)
    nft_content = nft_data['individual_content']

    bag_id = None
    if nft_content is not None:
        bag_id = nft_content.bag_id()
    return bag_id

async def _get_nft_torrent(address):
    bag_id = await _get_nft_bag_id(address)
    if bag_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)    
    
    result = await storage.node_get(bag_id)
    if result.get('error', None) == 'Query error: No such torrent':
        result = await storage.node_add(bag_id)
        if not 'error' in result:
            await asyncio.sleep(1)
            result = await storage.node_get(bag_id)    
    if 'error' in result:
        raise exceptions.TorrentClientError(result)
    return result


async def _torrent_apply_redundancy_policy(bag_id):
    peers = await storage.node_get_peers(bag_id)
    if 'error' in peers:
        return False

    replica_set = set(x['adnl_id'] for x in peers['peers'])
    if len(replica_set) >= settings.storage.min_redundancy:
        return
    
    logger.info("Apply redundancy policy to torrent, BAG Id: {bag_id}, replicas: {replicas}, min_redundancy: {min_redundancy}", 
                bag_id=bag_id, replicas=len(replica_set)+1, min_redundancy=settings.storage.min_redundancy) 
    node_state = await storage.get_node_state()
    random.shuffle(node_state)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=settings.storage.request_timeout * 2)) as session:
        for node in node_state:
            target_authority = node["ip_str"].split(':')[0]
            target_authority = f'{target_authority}:{settings.storage.gateway_port}'            
            try:
                logger.info("Add torrent to storage peer, ADNL: {adnl}, authority: {authority}, BAG Id: {bag_id}", 
                             adnl=node["adnl_id"], authority=target_authority, bag_id=bag_id)
                async with session.post(f'http://{target_authority}/storage/torrent/{bag_id}') as resp:
                    if resp.status == status.HTTP_200_OK:
                        replica_set.add(node["adnl_id"])
            except Exception as E: 
                logger.warning("Add torrent to storage peer error, ADNL: {adnl}, authority: {authority}, BAG Id: {bag_id}, exc: {exc}", 
                             adnl=node["adnl_id"], authority=target_authority, bag_id=bag_id, exc=str(E))
            if len(replica_set) >= settings.storage.min_redundancy:
                break


async def _confirm_nft_torrent(address, bag_id, timeout: float = 10):
    curr_time = st_time = time.monotonic()
    nft_bag_id = None
    while st_time + timeout > curr_time:
        await asyncio.sleep(10)
        nft_bag_id = await _get_nft_bag_id(address)
        if nft_bag_id == bag_id:
            break
        curr_time = time.monotonic()
    
    # if nft_bag_id != bag_id:
    #     logger.warning("Newly created NFT Torrent removed due to confirmation timeout, NFT: {address}, bag_id: {bag_id}", address=address, bag_id=bag_id)        
    #     await storage.node_remove(bag_id)
    #     return
    
    logger.warning("Newly created NFT Torrent confirmed, NFT: {address}, bag_id: {bag_id}", address=address, bag_id=bag_id)        
    await storage.node_upload_resume(bag_id)
    await _torrent_apply_redundancy_policy(bag_id)

