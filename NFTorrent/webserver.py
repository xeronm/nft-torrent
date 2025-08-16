import asyncio
import io
import logging
import logging.config
import os
import time
import hashlib
import base64
from mimetypes import guess_extension
from dataclasses import asdict
from typing import Any
from urllib.parse import urljoin

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse, Response

from NFTorrent.auth import ContractAPIKeyCookie, NodeJWTBearer
from NFTorrent.bot import Backend, BotApp
from NFTorrent.cache import DisabledCacheManager
from NFTorrent.imageutils import generate_cover, buffer_guess_type
from NFTorrent.indexer import IndexDb
from NFTorrent.ipfs import IpfsRpcManager
from NFTorrent.models import HealthCheckResult, NftContentState, torrent_digest
from NFTorrent.modelsbase import CollectionConfig
from NFTorrent.settings import Settings
from NFTorrent.tonlib import TonlibContractIsNotNft, TonlibManager
from NFTorrent.utils import dict_to_influx, guess_type, parse_ipfs_uri, uri_ipfs, uri_supported
from NFTorrent.locks import OperationLock

logger = logging.getLogger(__name__)

SPECIES_LOGO = [
    "Other",
    "Dog",
    "Cat",
    "Hamster",
    "Rabbit",
    "Parrot",
    "Fish",
    "Turtle",
    "Reptile",
    "Horse",
    "Hedgehog",
    "Mouse",
    "Ferret"
]


def image_data_response(image_data: bytes) -> StreamingResponse:
    hash = hashlib.md5(image_data).hexdigest().lower()
    media_type = buffer_guess_type(image_data, default_type="image/webp")[0]
    return StreamingResponse(
        io.BytesIO(image_data),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{hash}{guess_extension(media_type)}"',
            "ETag": hash
        },
    )


class Server:

    def __init__(self, settings: Settings = None, collection_config: CollectionConfig = None):
        self.settings = settings or Settings.from_environment()
        if self.settings.logger_config:
            logging.config.dictConfig(self.settings.logger_config)
        else:
            logging.basicConfig(level=self.settings.logger_level)

        self.collection_config = collection_config or self.settings.webserver.collection_config
        self.tonlib: TonlibManager = None
        self.indexer: IndexDb = None
        self.ipfs: IpfsRpcManager = None
        self.peer_hostnames = {}
        self.sync_wlock = {}
        self.loop = None

        self.jwt_bearer = NodeJWTBearer(
            subject=self.settings.webserver.public_addr or "127.0.0.1",
            jwt_secret=self.settings.webserver.jwt_secret,
            jwt_algorithm=self.settings.webserver.jwt_algorithm,
            real_ip_header=self.settings.webserver.real_ip_header,
            allow_networks=self.settings.webserver.allow_networks,
        )

        self.jwt_session = ContractAPIKeyCookie(
            jwt_secret=self.settings.webserver.jwt_secret,
            jwt_algorithm=self.settings.webserver.jwt_algorithm,
            real_ip_header=self.settings.webserver.real_ip_header,
            domains=self.settings.webserver.twa_domains,
            bot_token=self.settings.webserver.bot_token,
            allow_networks=self.settings.webserver.allow_networks,
        )

    async def startup(self):
        self.start_time = int(time.time())
        self.loop = loop = asyncio.get_event_loop()
        logger.warning("Server startup initiated...")
        logger.warning(
            "Parameters:\n"
            " - webserver.allow_networks: %s\n"
            " - webserver.api_root_path: %s\n"
            " - webserver.twa_domains: %s\n"
            " - webserver.allow_origins: %s\n"
            " - webserver.collections: %s <%s>\n"
            " - ipfs.enabled: %s\n"
            " - cache.enabled: %s <%s>\n"
            " - indexdb.enabled: %s\n",
            self.settings.webserver.allow_networks,
            self.settings.webserver.api_root_path,
            self.settings.webserver.twa_domains,
            self.settings.webserver.allow_origins,
            [x.address for x in self.settings.webserver.collection_config.collections],
            self.settings.webserver.collection_config.__importname__,
            self.settings.ipfs.enabled,
            self.settings.cache.enabled,
            self.settings.cache.manager_class.__importname__,
            self.settings.indexdb.enabled,
        )

        cache_manager = None
        if self.settings.cache.enabled:
            cache_manager = self.settings.cache.manager_class(cache_settings=self.settings.cache.cache_settings)
        else:
            cache_manager = DisabledCacheManager()

        if not self.settings.tonlib.liteserver_config_path:
            raise RuntimeError("Tonlib liteserver_config required")

        self.tonlib = TonlibManager(
            settings=self.settings.tonlib,
            cache_manager=cache_manager,
            loop=loop,
            collection_config=self.collection_config,
            logger_config=self.settings.logger_config,
        )

        if self.settings.ipfs.enabled:
            self.ipfs = IpfsRpcManager(self.settings.ipfs, cache_manager=cache_manager, tonlib=self.tonlib, loop=loop)

        self.bot_app = None
        if self.settings.indexdb.enabled:
            if self.settings.webserver.bot_token:
                self.bot_app = BotApp(
                    self.settings.webserver.bot_token,
                    backend=Backend(loop=loop, url=self.settings.indexdb.database_url, cache_manager=cache_manager),
                    admin_group_id=self.settings.webserver.bot_admin_group_id,
                    torrent_file_size_limit=self.settings.ipfs.file_size_limit,
                    node_id=self.settings.webserver.node_id,
                )
            self.indexer = IndexDb(
                self.settings.indexdb,
                bot_app=self.bot_app,
                bot_polling=self.settings.webserver.bot_polling,
                cache_manager=cache_manager,
                loop=loop,
                tonlib=self.tonlib,
                ipfs=self.ipfs,
                collection_config=self.collection_config,
            )

        await asyncio.sleep(3)  # wait for manager to spawn all workers and report their status

    async def shutdown(self):
        logger.warning("Server shutdown initiated...")
        if self.indexer is not None:
            await self.indexer.shutdown()

        waits = [self.tonlib.shutdown()]
        if self.ipfs is not None:
            waits.append(self.ipfs.shutdown())
        await asyncio.wait(waits, return_when=asyncio.ALL_COMPLETED)

    def _get_peer_uri(self, host: str, path: str):
        authority = f"{host}:{self.settings.webserver.port}" if self.settings.webserver.port else host
        api_root = self.settings.webserver.remote_api_root or self.settings.webserver.api_root_path
        schema = "https" if self.settings.webserver.enable_ssl else "http"
        return urljoin(urljoin(f"{schema}://{authority}", api_root) + "/", path)

    def _get_peer_headers(self, host: str):
        return {"Authorization": "Bearer " + self.jwt_bearer.get_jwt_token(host)}

    # API
    def get_healthcheck(self) -> HealthCheckResult:
        stotage_state = tonlib_state = indexer_state = None
        if self.tonlib is not None:
            tonlib_state = len([w for w in self.tonlib.workers.values() if w.is_sync]) >= 2  # 2 min liyterservers

        load = redundancy = 0
        if self.ipfs is not None:
            ipfs_state = self.ipfs.get_cached_node_state()
            if ipfs_state is not None:
                load = ipfs_state["storage"]["RepoSize"] * 100 / ipfs_state["storage"]["StorageMax"]
                redundancy = len(ipfs_state["cluster_peers"]) / self.settings.ipfs.min_redundancy
                stotage_state = ipfs_state["peers"] >= self.ipfs.settings.min_peers_count
        if self.indexer is not None:
            indexer_state = self.indexer.get_indexdb_state()
            last_checked = [x.last_checked for x in self.indexer.stats_coll.values()]
            indexer_state = len(last_checked) == len(
                [x for x in last_checked if x >= time.time() - self.indexer.settings.indexer_timeout * 2]
            )
        bot = False
        if self.bot_app is not None:
            bot = self.indexer.dp_active

        return HealthCheckResult(
            node_id=self.settings.webserver.node_id,
            tonlib=bool(tonlib_state),
            storage=bool(stotage_state),
            indexdb=bool(indexer_state),
            redundancy=round(redundancy, 2),
            bot=bot,
            load=round(load, 2),
        )

    def get_measurements(self, timestamp: int):
        hc = self.get_healthcheck()
        _stats = hc.model_dump()
        _stats["start_time"] = self.start_time
        node_id = _stats.pop("node_id")
        measurements = [f"NFTorrentServer,node={node_id} {dict_to_influx(_stats)} {timestamp}"]
        if self.tonlib is not None:
            measurements += self.tonlib.get_measurements(timestamp)
        if self.ipfs is not None:
            measurements += self.ipfs.get_measurements(timestamp)
        if self.indexer is not None:
            measurements += self.indexer.get_measurements(timestamp)
        return measurements

    async def get_nft_content(self, request: Request, address: str, query: str = None):
        nft_collection = self.collection_config.get_collection(address)
        if nft_collection is not None:
            if query == "uri":
                return JSONResponse(
                    nft_collection.meta,
                    headers={
                        "Content-Disposition": f'inline; filename="{address}.json"',
                    },
                )
            else:
                return FileResponse(
                    nft_collection.image,
                    media_type=guess_type(nft_collection.image, default_type="image/webp")[0],
                )

        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content

        uri = nft_content.uri() if query == "uri" else nft_content.image()
        if uri and uri_supported(uri):
            if uri_ipfs(uri):
                cid, file_path, digest = parse_ipfs_uri(uri)
                cid_info = await self.ipfs.get_cid_info(cid=cid)
                if not cid_info.files:
                    digest = cid_info.digest
                else:
                    file_info = None
                    if file_path or digest:
                        file_info = cid_info.get_file(filename=file_path, digest=digest)
                    if not file_info:
                        # fallback
                        _list = cid_info.list_types(mime_prefix="image/")
                        if _list is not None:
                            file_info = _list[0]
                    if not file_info:
                        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
                    digest = file_info.digest
                return RedirectResponse(request.url_for("get_nft_torrent_content", address=address, digest=digest))
            else:
                return RedirectResponse(uri)
        if nft_content.image_data() and query != "uri":
            return image_data_response(nft_content.image_data())
        if query == "uri":
            return JSONResponse({"attributes": nft_content.metadata_attributes()})

        nft_collection = self.collection_config.get_collection(nft_data.collection_address)
        if nft_collection.item_cover:
            kwargs = asdict(nft_collection.item_cover)
            species_name = (
                SPECIES_LOGO[nft_content.imm_data.species]
                if nft_content.imm_data.species < len(SPECIES_LOGO)
                else SPECIES_LOGO[0]
            )
            baseimage = os.path.join(kwargs.pop("baseimage_path"), f"{species_name}.webp")
            image = generate_cover(
                baseimage=baseimage, title=nft_content.title(), subtitle=nft_content.subtitle(), format="webp", **kwargs
            )
            return image_data_response(image)

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    async def get_nft_torrent_content(self, address: str = None, file_path: str = None, digest: str = None):
        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content
        if nft_content is not None:
            image = nft_content.image()
            if uri_ipfs(image):
                cid, _, _ = parse_ipfs_uri(image)
                data, info = await self.ipfs.get_cid_file(cid=cid, file_path=file_path, digest=digest)
                return StreamingResponse(
                    io.BytesIO(data),
                    headers={
                        "Content-Disposition": f'inline; filename="{info.name}"',
                        "ETag": info.hash,
                    },
                    media_type=guess_type(info.name, default_type="image/webp")[0],
                )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    async def sync_nft_data(self, address: str = None):
        async with OperationLock(f'sync:{address}', self.sync_wlock, wait=False):
            await asyncio.sleep(7)  # wait for cache expiration
            try:
                # Ownership is not verified here, since the NFT may have been transferred or deleted.
                nft_data = await self.tonlib.get_nft_data(address)
            except TonlibContractIsNotNft:
                nft_data = None
                account_state = await self.tonlib.generic_get_account_state(address)
                if account_state["account_state"]["@type"] == "uninited.accountState":
                    # looks as if NFT was destroyed
                    await self.indexer.nft_update_nft_data(address)
                    return
                raise

            nft_content = nft_data.individual_content
            if nft_content is not None:
                image = nft_content.image()
                if uri_ipfs(image):
                    cid, _, _ = parse_ipfs_uri(image)
                    if cid:
                        pin_status = await self.ipfs.cid_pin_status(cid=cid)
                        if nft_content.storage_due_time() > (pin_status.expires if pin_status else time.time()):
                            self.loop.create_task(self.ipfs.confirm_content(address, old_cid=None, cid=cid))
                await self.indexer.nft_update_nft_data(address, nft_data)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def get_nft_cid_info(self, address: str, digest: str = None):
        cid, _ = await self.ipfs.get_nft_cid(address, raise_error=True)
        if digest and digest != torrent_digest(cid):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        response = await self.ipfs.get_cid_info(cid=cid)
        if digest and response.state == NftContentState.READY:
            return JSONResponse(
                jsonable_encoder(response),
                headers={"Cache-Control": "public, max-age=864000, immutable", "ETag": response.hash},
            )

        return JSONResponse(jsonable_encoder(response))

    async def get_nft_cid_pin(self, address: str, digest: str = None):
        cid, _ = await self.ipfs.get_nft_cid(address, raise_error=True)
        if digest and digest != torrent_digest(cid):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        pin_status = await self.ipfs.cid_pin_status(cid)
        if not pin_status:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return pin_status

    async def register_tg_user(self, owner: str = None, userdata: Any = None, country: str = None):
        if owner is None or userdata is None or not isinstance(userdata, dict):
            return
        user_id = userdata.get("id")
        is_premium = userdata.get("prem")
        username = userdata.get("name")
        language = userdata.get("lang", "en")
        if user_id:
            await self.indexer.register_tg_user(
                owner=owner,
                user_id=user_id,
                username=username,
                is_premium=is_premium,
                language=language,
                country=country,
            )
