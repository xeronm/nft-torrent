import asyncio
from functools import wraps

from fastapi import FastAPI
from fastapi.exceptions import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi import status
from fastapi.params import Depends

from pytonlib import TonlibException

from NFTorrent import __meta__
from NFTorrent import models
from NFTorrent.webserver import Server

from loguru import logger

ws = Server()

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
    root_path=ws.settings.webserver.api_root_path,
    openapi_tags=tags_metadata
)



@app.on_event("startup")
async def startup():
    await ws.startup()


@app.on_event("shutdown")
async def shutdown_event():
    await ws.shutdown()


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
        result = await asyncio.wait_for(func(*args, **kwargs), ws.settings.webserver.request_timeout)
        return result
    return wrapper


# API
@app.get('/healthcheck', include_in_schema=False)
async def healthcheck():
    return await ws.get_healthcheck()


@app.get('/tonlib/state', dependencies=[Depends(ws.jwt_bearer)], tags=['liteserver'])
@wrap_result
async def get_tonlib_worker_state():
    """
    Get liteservers state.
    """       
    return ws.tonlib.get_workers_state()


@app.get('/storage/state', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'])
@wrap_result
async def get_storage_state():
    """
    Get storage state.
    """    
    return ws.storage.get_storage_state()


@app.get('/storage/peers', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'])
@wrap_result
async def get_storage_node_peers():
    """
    Get storage remote peers state.
    """    
    return await ws.storage.get_node_state()


@app.get('/storage/peers/{adnl_id}', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'])
@wrap_result
async def get_storage_node_peer_state(request: models.StoragePeerMethod = Depends()):
    """
    Get storage remote peer information.
    """    
    return await ws.get_storage_peer_state(request.adnl_id, '/storage/state')



@app.get('/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)], response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Get Torrent information.
    """
    result = await ws.storage.node_get(request.bag_id)
    return result

@app.get('/storage/torrent/{bag_id}/peers', dependencies=[Depends(ws.jwt_bearer)], response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent_peers(request: models.StorageTorrentMethod = Depends()):
    """
    Get Torrent peers information.
    """
    result = await ws.storage.node_get_peers(request.bag_id)
    return result


@app.post('/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)], response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def add_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Add Torrent.
    """
    # TODO Validate adnl_id and ip_str
    result = await ws.storage.node_add(request.bag_id)
    return result


@app.get('/nft/{address}', response_model_exclude_none=True, tags=['nft'])
@wrap_result
async def get_nft_data(request: models.NftMethod = Depends()):
    """
    Get NFT Data information.
    """
    return await ws.tonlib.get_nft_data(request.address)


@app.get('/nft/{address}/torrent', response_model_exclude_none=True, tags=['nft-torrent'])
@wrap_result
async def get_nft_torrent(request: models.NftMethod = Depends()):
    """
    Get NFT Torrent information.
    """
    return await ws._get_nft_torrent(request.address)


@app.get('/nft/{address}/torrent/{file_path:path}', response_model_exclude_none=True, tags=['nft-torrent'])
@wrap_result
async def get_nft_torrent_file(request: models.NftStorageTorrentMethod = Depends()):
    """
    Get NFT Torrent File.
    """
    filename = await ws.get_nft_torrent_filename(request.address, request.file_path)    
    return FileResponse(path=filename)


@app.post('/nft/{address}/torrent', response_model_exclude_none=True, tags=['nft-torrent'])
async def create_nft_torrent(request: models.NftTorrentCreate = Depends()):
    """
    Create NFT Torrent.
    """
    return await ws.create_nft_torrent(request.address, request.files)