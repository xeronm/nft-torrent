import asyncio
import time
from functools import wraps

import aiohttp
import aiohttp.client_exceptions
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Depends
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import ValidationError
from pytonlib import TonlibException
from starlette.exceptions import HTTPException as StarletteHTTPException

from NFTorrent import __meta__, models
from NFTorrent.auth import set_cookie
from NFTorrent.ipfs import IpfsRpcHttpException
from NFTorrent.middlewares import StatisticsMiddleware, StatisticsStore
from NFTorrent.tonlib import TonlibRequestError
from NFTorrent.webserver import Server

ws = Server()

tags_metadata = []

app = FastAPI(
    title=__meta__.__title__,
    description=__meta__.__description__,
    version=__meta__.__version__,
    docs_url="/",
    responses={422: {"description": "Validation Error"}, 504: {"description": "Server Timeout"}},
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


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request, exc):
    res = models.ProblemDetail(
        title=type(exc).__name__,
        detail="Request validation failed, see errors for details",
        errors=[{k: v for k, v in err.items() if k != "ctx"} for err in exc.errors()],
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc):
    res = models.ProblemDetail(
        title=type(exc).__name__,
        detail="Request validation failed, see errors for details",
        errors=[{k: v for k, v in err.items() if k != "ctx"} for err in exc.errors()],
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.exception_handler(aiohttp.client_exceptions.ClientError)
async def client_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_502_BAD_GATEWAY)


@app.exception_handler(aiohttp.client_exceptions.ClientConnectorError)
async def client_connect_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_502_BAD_GATEWAY)


@app.exception_handler(asyncio.TimeoutError)
async def timeout_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_504_GATEWAY_TIMEOUT)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_504_GATEWAY_TIMEOUT)


@app.exception_handler(TonlibException)
async def tonlib_error_result_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.exception_handler(IpfsRpcHttpException)
async def ipfs_exception_handler(request, exc):
    res = models.ProblemDetail(title=type(exc).__name__, detail=str(exc), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return JSONResponse(res.dict(exclude_none=True), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.exception_handler(TonlibRequestError)
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
    allow_origins=ws.settings.webserver.allow_origins,
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
@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> models.HealthCheckResult:
    return ws.get_healthcheck()


@app.get("/stats", response_class=PlainTextResponse, include_in_schema=False)
async def statistics(request: Request) -> str:
    timestamp = int(time.time() * 1000000000)
    measurements = ws.get_measurements(timestamp)
    measurements += stats.as_influx(timestamp)
    return "\n".join(measurements)


@app.get(
    "/api/v1/tonlib/state",
    dependencies=[Depends(ws.jwt_bearer)],  # noqa: B008
    tags=["liteserver"],
    response_model=models.TonlibManagerState,
)
@wrap_result
async def get_tonlib_state():
    """
    Get liteservers state.
    """
    return ws.tonlib.get_tonlib_state()


@app.get(
    "/api/v1/ipfs/state",
    dependencies=[Depends(ws.jwt_bearer)],  # noqa: B008
    tags=["ipfs"],
    response_model=models.IpfsNodeState,
)
@wrap_result
async def get_ipfs_state():
    """
    Get IPFS state.
    """
    return ws.ipfs.get_cached_node_state()


if ws.settings.indexdb.enabled:

    @app.get(
        "/api/v1/indexdb/state",
        dependencies=[Depends(ws.jwt_bearer)],  # noqa: B008
        tags=["indexdb"],
        response_model=models.IndexDbState,
    )
    @wrap_result
    async def get_indexdb_state():
        """
        Get IndexDB state.
        """
        return ws.indexer.get_indexdb_state()


@app.get("/api/v1/account/authPayload", tags=["account"])
async def get_account_auth_payload(request: Request) -> models.AuthPayload:
    """
    Get authentication payload
    """
    return models.AuthPayload(payload=ws.jwt_session.get_auth_payload(init_data=dict(request.query_params)))


@app.post("/api/v1/account/auth", tags=["account"])
async def create_account_auth_session(rawRequest: Request, body: models.AuthData) -> models.AuthSession:
    """
    Auhtenticate account signature and create session
    """
    payload, token = ws.jwt_session.auth_session(body.account, body.proof)
    response = JSONResponse(
        models.AuthSession(node=ws.get_healthcheck(), sess=payload).dict(), status_code=status.HTTP_200_OK
    )
    await ws.register_tg_user(
        owner=payload.sub, userdata=payload.user, country=rawRequest.headers.get("x-country-code")
    )
    set_cookie(
        response,
        ws.jwt_session.cookie_name,
        token,
        expires=payload.exp,
        secure=True,
        httponly=True,
        samesite="none",
        partitioned=True,
    )
    return response


@app.get("/api/v1/account/auth", tags=["account"])
async def get_account_auth_session(
    jwt_payload: models.JWTPayload = Depends(ws.jwt_session),  # noqa: B008
) -> models.AuthSession:
    """
    Get authenticated session state
    """
    return models.AuthSession(node=ws.get_healthcheck(), sess=jwt_payload if jwt_payload is not None else None)


@app.get("/c/{address}", response_model_exclude_none=True, tags=["nft-content"])
@wrap_result
async def get_nft_content(
    rawRequest: Request, request: models.NftContentMethod = Depends()  # noqa: B008
) -> FileResponse:  # noqa: B008
    """
    Get NFT standard content.
    """
    response = await ws.get_nft_content(rawRequest, request.address, query=request.q)
    if isinstance(response, Response):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.get("/c/{address}/{digest}", response_model_exclude_none=True, tags=["nft-content"])
@wrap_result
async def get_nft_torrent_content(request: models.BaseNftContentMethod = Depends()) -> FileResponse:  # noqa: B008
    """
    Get NFT torrent content by digest.
    """
    response = await ws.get_nft_torrent_content(request.address, digest=request.digest)
    if isinstance(response, Response):
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"
    return response


@app.get(
    "/api/v1/nft/{address}",
    response_model_exclude_none=True,
    dependencies=[Depends(ws.jwt_session)],  # noqa: B008
    tags=["nft"],
)
@wrap_result
async def get_nft_data(request: models.NftMethod = Depends()) -> models.NftItemData:  # noqa: B008
    """
    Get NFT Data information.
    """
    nft_data = await ws.tonlib.get_nft_data(request.address)
    return nft_data


@app.get(
    "/api/v1/nft/{address}/address",
    response_model_exclude_none=True,
    dependencies=[Depends(ws.jwt_session)],  # noqa: B008
    tags=["nft"],
)
@wrap_result
async def get_nft_address_information(request: models.NftMethod = Depends()):  # noqa: B008
    """
    Get NFT Address information.
    """
    nft_state = await ws.tonlib.generic_get_account_state(request.address)
    nft_state.pop("data", None)
    nft_state.pop("code", None)
    return nft_state


@app.post("/api/v1/nft/{address}/sync", response_model_exclude_none=True, tags=["nft"])
async def sync_nft_data(
    rawRequest: Request,
    request: models.NftMethod = Depends(),  # noqa: B008
    jwt_payload: models.JWTPayload = Depends(ws.jwt_session),  # noqa: B008
):
    """
    Sync NFT OffChain data.
    """
    if jwt_payload is not None:
        await ws.register_tg_user(
            owner=jwt_payload.sub, userdata=jwt_payload.user, country=rawRequest.headers.get("x-country-code")
        )
        return await ws.sync_nft_data(request.address, owner=jwt_payload.sub, userdata=jwt_payload.user)
    else:
        return await ws.sync_nft_data(request.address)


@app.get(
    "/api/v1/nft/{address}/content/{file_path:path}",
    response_model_exclude_none=True,
    dependencies=[Depends(ws.jwt_session)],
    tags=["nft"],
)
@wrap_result
async def get_nft_ipfs_content_file(
    request: models.NftStorageTorrentMethod = Depends(),  # noqa: B008
) -> FileResponse:  # noqa: B008
    """
    Get NFT Content File.
    """
    return await ws.get_nft_torrent_content(address=request.address, file_path=request.file_path)


if ws.settings.ipfs.enabled:

    @app.get(
        "/api/v1/nft/{address}/ipfs/{digest}",
        response_model_exclude_none=True,
        dependencies=[Depends(ws.jwt_session)],  # noqa: B008
        tags=["nft"],
    )
    @wrap_result
    async def get_nft_ipfs_cid(request: models.BaseNftContentMethod = Depends()):  # noqa: B008
        """
        Get NFT IPFS CID information.
        """
        return await ws.get_nft_cid_info(request.address, request.digest)

    @app.get(
        "/api/v1/nft/{address}/ipfs/{digest}/pin",
        response_model_exclude_none=True,
        dependencies=[Depends(ws.jwt_session)],  # noqa: B008
        tags=["nft"],
    )
    @wrap_result
    async def get_nft_ipfs_cid_pin(request: models.BaseNftContentMethod = Depends()):  # noqa: B008
        """
        Get NFT IPFS CID Pin status.
        """
        return await ws.get_nft_cid_pin(request.address, request.digest)

    @app.post("/api/v1/nft/ipfs", response_model_exclude_none=True, tags=["nft"])
    async def create_new_nft_ipfs_content(
        rawRequest: Request,
        request: models.NewNftTorrentCreate = Depends(),  # noqa: B008
        jwt_payload: models.JWTPayload = Depends(ws.jwt_session),  # noqa: B008
    ):
        """
        Create new NFT IPFS Content.
        """
        result = await ws.ipfs.new_nft_create_content(
            request.files, owner=jwt_payload.sub if jwt_payload is not None else None
        )
        if jwt_payload is not None:
            await ws.register_tg_user(
                owner=jwt_payload.sub, userdata=jwt_payload.user, country=rawRequest.headers.get("x-country-code")
            )
        return result

    @app.post("/api/v1/nft/{address}/ipfs", response_model_exclude_none=True, tags=["nft"])
    async def create_nft_ipfs_content(
        rawRequest: Request,
        request: models.NftTorrentCreate = Depends(),  # noqa: B008
        jwt_payload: models.JWTPayload = Depends(ws.jwt_session),  # noqa: B008
    ):
        """
        Create NFT IPFS Content.
        """
        result = await ws.ipfs.create_content(
            request.address, request.files, owner=jwt_payload.sub if jwt_payload is not None else None
        )
        if jwt_payload is not None:
            await ws.register_tg_user(
                owner=jwt_payload.sub, userdata=jwt_payload.user, country=rawRequest.headers.get("x-country-code")
            )
        return result


if ws.settings.indexdb.enabled:

    @app.get(
        "/api/v1/collection",
        response_model_exclude_none=True,
        tags=["collection"],
        # dependencies=[Depends(ws.jwt_session)],  # noqa: B008
    )
    async def list_collections() -> list[models.CollectionData]:
        """
        List Collections Info.
        """
        return [
            x.collection_data if x.collection_data else await ws.tonlib.get_collection_data(x.nft_collection.address)
            for x in ws.indexer.collections.values()
        ]

    @app.get(
        "/api/v1/collection/items",
        response_model_exclude_none=True,
        tags=["collection"],
        dependencies=[Depends(ws.jwt_session)],  # noqa: B008
    )
    async def list_collection_nft_items(
        request: models.CollectionItemsMethod = Depends(),  # noqa: B008
    ) -> list[models.NftItemHeader]:
        """
        List Collection NFT items.
        """
        return await ws.indexer.collection_query(**request.dict())

    @app.get("/api/v1/collection/feed", response_model_exclude_none=True, tags=["collection"])
    async def collection_random_feed(
        request: models.CollectionItemsMethod = Depends(),  # noqa: B008
    ) -> list[models.NftItemHeader]:
        """
        Collection NFT radnom feed.
        """
        return await ws.indexer.collection_random_feed(**request.dict())
