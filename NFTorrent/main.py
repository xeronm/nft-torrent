import asyncio
from functools import wraps
from typing import List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi import status
from fastapi.params import Depends

from pytonlib import TonlibException

from NFTorrent import __meta__
from NFTorrent import models
from NFTorrent.webserver import Server
from NFTorrent.auth import JWTPayload
from NFTorrent.middlewares import StatisticsMiddleware, StatisticsStore

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
        504: {'description': 'Server Timeout'}
    },
    root_path=ws.settings.webserver.api_root_path,
    openapi_tags=tags_metadata,
)

stats = StatisticsStore()

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


@app.middleware("http")
async def add_bearer_response_auth_header(request: Request, call_next):
    request.state.bearer_auth_client_ip = None
    response = await call_next(request)
    if request.state.bearer_auth_client_ip:
        response.headers[ws.jwt_bearer.response_header] = ws.jwt_bearer.get_jwt_token(request.state.bearer_auth_client_ip)
    return response


app.add_middleware(StatisticsMiddleware, stats_store=stats)


def wrap_result(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = await asyncio.wait_for(func(*args, **kwargs), ws.settings.webserver.request_timeout)
        return result
    return wrapper


# API
@app.get('/healthcheck', include_in_schema=False)
async def healthcheck() -> models.HealthCheckResult:
    return await ws.get_healthcheck()

@app.get('/stats', include_in_schema=False)
async def healthcheck():
    return stats.as_list()


@app.get('/tonlib/state', dependencies=[Depends(ws.jwt_bearer)], tags=['liteserver'], 
         response_model=models.TonlibManagerState, )
@wrap_result
async def get_tonlib_state():
    """
    Get liteservers state.
    """       
    return {
        'liteservers': ws.tonlib.get_workers_state()
    }


@app.get('/storage/state', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'],
         response_model=models.StorageManagerState)
@wrap_result
async def get_storage_state():
    """
    Get storage state.
    """    
    result = ws.storage.get_storage_state()
    result['stats'].update(ws.stats)
    return result


@app.get('/storage/peer', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'],
         response_model=List[models.NodePeerInfo])
@wrap_result
async def get_storage_node_peers():
    """
    Get storage remote peers state.
    """    
    return await ws.storage.get_node_state()


@app.get('/storage/peer/{adnl_id}', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'])
@wrap_result
async def get_storage_node_peer_state(request: models.StoragePeerMethod = Depends()):
    """
    Get storage remote peer information.
    """    
    return await ws.get_storage_peer_state(request.adnl_id, '/storage/state')


@app.get('/storage/torrent', dependencies=[Depends(ws.jwt_bearer)], 
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent():
    """
    List Torrents.
    """
    result = await ws.storage.node_list()
    return result


@app.get('/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)], 
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Get Torrent information.
    """
    result = await ws.storage.node_get(request.bag_id)
    return result


@app.get('/storage/torrent/{bag_id}/c/{digest}', dependencies=[Depends(ws.jwt_bearer)], 
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent_content(request: models.StorageTorrentContentMethod = Depends()):
    """
    Get Torrent content.
    """
    response = await ws.get_nft_torrent_content(bag_id=request.bag_id, digest=request.digest)
    return response


@app.get('/storage/torrent/{bag_id}/peer', dependencies=[Depends(ws.jwt_bearer)], 
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent_peers(request: models.StorageTorrentMethod = Depends()):
    """
    Get Torrent peers information.
    """
    result = await ws.storage.node_get_peers(request.bag_id)
    return result


@app.post('/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)], 
          response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def add_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Add Torrent.
    """
    return await ws.add_torrent(request.bag_id)


@app.delete('/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)], 
          response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def remove_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Remove Torrent.
    """
    result = await ws.remove_torrent(request.bag_id)
    return result


@app.get('/account/authPayload', tags=['account'])
async def get_account_auth_payload() -> models.AuthPayload:
    """
    Get authentication payload
    """
    return models.AuthPayload(payload=ws.jwt_session.get_auth_payload())


@app.post('/account/auth', tags=['account'])
async def create_account_auth_session(body: models.AuthData) -> Optional[str]:
    """
    Auhtenticate account signature and create session 
    """
    return ws.jwt_session.auth_session(body.account, body.proof) or "Ok"

@app.get('/account/auth', tags=['account'])
async def get_account_auth(jwt_payload: JWTPayload = Depends(ws.jwt_session)) -> Optional[JWTPayload]:
    """
    Verify session token
    """
    return jwt_payload if jwt_payload is not None else None


@app.get('/c/{address}', response_model_exclude_none=True, tags=['nft-content'])
@wrap_result
async def get_nft_content_default_image(request: models.NftMethod = Depends()) -> FileResponse:
    """
    Get NFT default content image.
    """
    return await ws.get_default_image(request.address)


@app.get('/c/{address}/{digest}', response_model_exclude_none=True, tags=['nft-content'])
@wrap_result
async def get_nft_content(request: models.NftContentMethod = Depends()) -> FileResponse:
    """
    Get NFT content by digest.
    """
    return await ws.get_nft_torrent_content(request.address, digest=request.digest)


@app.get('/nft/{address}', response_model_exclude_none=True, dependencies=[Depends(ws.jwt_session)], tags=['nft'])
@wrap_result
async def get_nft_data(request: models.NftMethod = Depends()):
    """
    Get NFT Data information.
    """
    nft_data, _ = await ws.tonlib.get_nft_data(request.address)
    return nft_data


@app.get('/nft/{address}/torrent', response_model_exclude_none=True, dependencies=[Depends(ws.jwt_session)], tags=['nft'])
@wrap_result
async def get_nft_torrent(request: models.NftMethod = Depends()):
    """
    Get NFT Torrent information.
    """
    return await ws.get_nft_torrent(request.address)


@app.get('/nft/{address}/torrent/{file_path:path}', response_model_exclude_none=True, dependencies=[Depends(ws.jwt_session)], tags=['nft'])
@wrap_result
async def get_nft_torrent_file(request: models.NftStorageTorrentMethod = Depends()) -> FileResponse:
    """
    Get NFT Torrent File.
    """
    return await ws.get_nft_torrent_content(request.address, request.file_path)    


@app.post('/nft/{address}/torrent', response_model_exclude_none=True, tags=['nft'])
async def create_nft_torrent(request: models.NftTorrentCreate = Depends(), jwt_payload: JWTPayload = Depends(ws.jwt_session)):
    """
    Create NFT Torrent.
    """
    return await ws.create_nft_torrent(request.address, request.files, owner=jwt_payload.sub if jwt_payload is not None else None)