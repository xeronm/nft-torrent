import asyncio
import dataclasses
import time
from functools import wraps
from typing import Dict, List

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.params import Depends
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pytonlib import TonlibException
from starlette.exceptions import HTTPException as StarletteHTTPException

from NFTorrent import __meta__, models
from NFTorrent.middlewares import StatisticsMiddleware, StatisticsStore
from NFTorrent.pyTON.manager import ContractRequestError
from NFTorrent.webserver import Server

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


def dataclass_to_influx(instance):
    kv = []
    for field in dataclasses.fields(instance):
        value = getattr(instance, field.name, None)
        if value is None:
            continue
        if issubclass(field.type, str):
            value = '"' + value.replace('"', '\\"') + '"'
        kv.append(f'{field.name}={value}')
    return ','.join(kv)


def dict_to_influx(instance: Dict):
    kv = []
    for k, v in instance.items():
        value = v
        if value is None:
            continue
        if isinstance(v, dict):
            continue
        elif isinstance(v, bool):
            value = int(value)
        elif isinstance(v, str):
            value = '"' + value.replace('"', '\\"') + '"'
        kv.append(f'{k}={value}')
    return ','.join(kv)


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


@app.exception_handler(RequestValidationError)
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


@app.exception_handler(ContractRequestError)
async def invalid_contract_result_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_400_BAD_REQUEST)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_400_BAD_REQUEST)


@app.exception_handler(Exception)
async def fastapi_generic_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@app.middleware("http")
async def add_bearer_response_auth_header(request: Request, call_next):
    request.state.bearer_auth_client_ip = None
    response = await call_next(request)
    if request.state.bearer_auth_client_ip:
        jwt_token = ws.jwt_bearer.get_jwt_token(request.state.bearer_auth_client_ip)
        response.headers[ws.jwt_bearer.response_header] = jwt_token
    return response


app.add_middleware(StatisticsMiddleware, stats_store=stats)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ws.settings.webserver.twa_domains,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get('/stats', response_class=PlainTextResponse, include_in_schema=False)
async def statistics(request: Request):
    _timestamp = int(time.time() * 1000000)

    tonlib = ws.tonlib.get_tonlib_state()
    liteservers_stats = [
        f'NFTorrentLiteservers,{dict_to_influx({"id": ls["ls_index"]})} {dict_to_influx(ls)} {_timestamp}'
        for ls in tonlib['workers'].values()
    ]

    storage = ws.storage.get_storage_state()
    _storage = {
        'size': storage['size'],
        'max_size': storage['max_size'],
        'size_pressure': storage['size_pressure'],
    }
    _storage.update(storage["stats"])
    _storage.update(ws.stats)

    workers_stats = [
        f'NFTorrentStorageWorkers,{dict_to_influx({"id": w["client_id"]})} {dict_to_influx(w)} {_timestamp}'
        for w in storage['workers'].values()
    ]

    http_stats = [
        f'NFTorrentHttp,{dataclass_to_influx(k)} {dataclass_to_influx(v)} {_timestamp}'
        for k, v in stats.items()
    ]

    indexer_stats = []
    if ws.indexer is not None:
        indexer_stats = [
            f'NFTorrentIndexer,address={k} {dict_to_influx(dict(**item["stats"], next_index=item["next_index"]))} {_timestamp}'  # noqa: E501
            for k, item in ws.indexer.get_indexdb_state().items()
        ]

    return '\n'.join([
        f'NFTorrentStorage {dict_to_influx(_storage)} {_timestamp}',
        f'NFTorrentTonlib {dict_to_influx(tonlib["stats"])} {_timestamp}',
    ] + workers_stats + liteservers_stats + indexer_stats + http_stats)


@app.get('/api/v1/tonlib/state', dependencies=[Depends(ws.jwt_bearer)], tags=['liteserver'],
         response_model=models.TonlibManagerState, )
@wrap_result
async def get_tonlib_state():
    """
    Get liteservers state.
    """
    return ws.tonlib.get_tonlib_state()


@app.get('/api/v1/indexdb/state', dependencies=[Depends(ws.jwt_bearer)], tags=['indexdb'],
         response_model=models.IndexDbState, )
@wrap_result
async def get_indexdb_state():
    """
    Get IndexDB state.
    """
    return {'collections': ws.indexer.get_indexdb_state()}


@app.get('/api/v1/storage/state', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'],
         response_model=models.StorageManagerState)
@wrap_result
async def get_storage_state():
    """
    Get storage state.
    """
    result = ws.storage.get_storage_state()
    _storage_stats = {}
    _storage_stats.update(result["stats"])
    _storage_stats.update(ws.stats)
    result['stats'] = _storage_stats
    return result


@app.get('/api/v1/storage/peer', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'],
         response_model=List[models.NodePeerInfo])
@wrap_result
async def get_storage_node_peers():
    """
    Get storage remote peers state.
    """
    return await ws.storage.get_node_state()


@app.get('/api/v1/storage/peer/{adnl_id}', dependencies=[Depends(ws.jwt_bearer)], tags=['storage'])
@wrap_result
async def get_storage_node_peer_state(request: models.StoragePeerMethod = Depends()):
    """
    Get storage remote peer information.
    """
    return await ws.get_storage_peer_state(request.adnl_id, '/api/v1/storage/state')


@app.get('/api/v1/storage/torrent', dependencies=[Depends(ws.jwt_bearer)],
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def list_torrents():
    """
    List Torrents.
    """
    result = await ws.storage.node_list()
    return result


@app.get('/api/v1/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)],
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Get Torrent information.
    """
    result = await ws.storage.node_get(request.bag_id)
    return result


@app.get('/api/v1/storage/torrent/{bag_id}/c/{digest}', dependencies=[Depends(ws.jwt_bearer)],
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent_content(request: models.StorageTorrentContentMethod = Depends()):
    """
    Get Torrent content.
    """
    response = await ws.get_nft_torrent_content(bag_id=request.bag_id, digest=request.digest)
    return response


@app.get('/api/v1/storage/torrent/{bag_id}/peer', dependencies=[Depends(ws.jwt_bearer)],
         response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def get_torrent_peers(request: models.StorageTorrentMethod = Depends()):
    """
    Get Torrent peers information.
    """
    result = await ws.storage.node_get_peers(request.bag_id)
    return result


@app.post('/api/v1/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)],
          response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def add_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Add Torrent.
    """
    return await ws.add_torrent(request.bag_id)


@app.delete('/api/v1/storage/torrent/{bag_id}', dependencies=[Depends(ws.jwt_bearer)],
            response_model_exclude_none=True, tags=['storage'])
@wrap_result
async def remove_torrent(request: models.StorageTorrentMethod = Depends()):
    """
    Remove Torrent.
    """
    result = await ws.remove_torrent(request.bag_id)
    return result


@app.get('/api/v1/account/authPayload', tags=['account'])
async def get_account_auth_payload() -> models.AuthPayload:
    """
    Get authentication payload
    """
    return models.AuthPayload(payload=ws.jwt_session.get_auth_payload())


@app.post('/api/v1/account/auth', tags=['account'])
async def create_account_auth_session(body: models.AuthData) -> models.AuthSession:
    """
    Auhtenticate account signature and create session
    """
    payload, token = ws.jwt_session.auth_session(body.account, body.proof)
    response = JSONResponse(models.AuthSession(node=await ws.get_healthcheck(), sess=payload).dict(),
                            status_code=status.HTTP_200_OK)
    response.set_cookie(ws.jwt_session.cookie_name, token, expires=payload.exp, secure=True, httponly=True)
    return response


@app.get('/api/v1/account/auth', tags=['account'])
async def get_account_auth_session(jwt_payload: models.JWTPayload = Depends(ws.jwt_session)) -> models.AuthSession:
    """
    Get authenticated session state
    """
    return models.AuthSession(node=await ws.get_healthcheck(), sess=jwt_payload if jwt_payload is not None else None)


@app.get('/c/{address}', response_model_exclude_none=True, tags=['nft-content'])
@wrap_result
async def get_nft_content_default_image(request: models.NftMethod = Depends()) -> FileResponse:
    """
    Get NFT default content image.
    """
    return await ws.get_default_image(request.address)


@app.get('/c/{address}/{digest}', response_model_exclude_none=True, tags=['nft-content'])
@wrap_result
async def get_nft_content(request: models.BaseNftContentMethod = Depends()) -> FileResponse:
    """
    Get NFT content by digest.
    """
    return await ws.get_nft_torrent_content(request.address, digest=request.digest)


@app.get('/api/v1/nft/{address}',
         response_model_exclude_none=True,
         dependencies=[Depends(ws.jwt_session)], tags=['nft'])
@wrap_result
async def get_nft_data(request: models.NftMethod = Depends()) -> models.NftItemData:
    """
    Get NFT Data information.
    """
    nft_data = await ws.tonlib.get_nft_data(request.address)
    return nft_data


@app.get('/api/v1/nft/{address}/address',
         response_model_exclude_none=True,
         dependencies=[Depends(ws.jwt_session)], tags=['nft'])
@wrap_result
async def get_nft_address_information(request: models.NftMethod = Depends()):
    """
    Get NFT Address information.
    """
    return await ws.tonlib.raw_get_account_state(request.address)


@app.get('/api/v1/nft/{address}/torrent',
         response_model_exclude_none=True,
         dependencies=[Depends(ws.jwt_session)], tags=['nft'])
@wrap_result
async def get_nft_torrent(request: models.NftMethod = Depends()):
    """
    Get NFT Torrent information.
    """
    return await ws.get_nft_torrent(request.address)


@app.get('/api/v1/nft/{address}/torrent/{file_path:path}',
         response_model_exclude_none=True,
         dependencies=[Depends(ws.jwt_session)], tags=['nft'])
@wrap_result
async def get_nft_torrent_file(request: models.NftStorageTorrentMethod = Depends()) -> FileResponse:
    """
    Get NFT Torrent File.
    """
    return await ws.get_nft_torrent_content(request.address, request.file_path)


@app.post('/api/v1/nft/{address}/torrent', response_model_exclude_none=True, tags=['nft'])
async def create_nft_torrent(request: models.NftTorrentCreate = Depends(),
                             jwt_payload: models.JWTPayload = Depends(ws.jwt_session)):
    """
    Create NFT Torrent.
    """
    return await ws.create_nft_torrent(request.address, request.files,
                                       owner=jwt_payload.sub if jwt_payload is not None else None)


if ws.settings.indexdb.enabled:
    @app.get('/api/v1/collection', response_model_exclude_none=True, tags=['collection'],
             dependencies=[Depends(ws.jwt_session)])
    async def list_collections() -> List[models.CollectionData]:
        """
        List Collections Info.
        """
        return [
            x.collection_data if x.collection_data else
            await ws.tonlib.get_collection_data(x.nft_collection.address)
            for x in ws.indexer.collections.values()
        ]

    @app.get('/api/v1/collection/items', response_model_exclude_none=True, tags=['collection'],
             dependencies=[Depends(ws.jwt_session)])
    async def list_collection_nft_items(request: models.CollectionItemsMethod = Depends()) -> List[models.NftItemHeader]:  # noqa: E501
        """
        List Collection NFT items.
        """
        return await ws.indexer.collection_query(**request.dict())

    @app.get('/api/v1/collection/feed', response_model_exclude_none=True, tags=['collection'])
    async def collection_random_feed(request: models.CollectionItemsMethod = Depends()) -> List[models.NftItemHeader]:
        """
        Collection NFT radnom feed.
        """
        return await ws.indexer.collection_random_feed(**request.dict())
