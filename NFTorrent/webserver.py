import asyncio
import io
import logging
import logging.config
import time
from urllib.parse import urljoin

from fastapi import Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder

from NFTorrent.auth import ContractAPIKeyCookie, NodeJWTBearer
from NFTorrent.cache import DisabledCacheManager
from NFTorrent.indexer import IndexDb
from NFTorrent.ipfs import IpfsRpcManager
from NFTorrent.models import HealthCheckResult, NftContentState, NftContentPin, torrent_digest
from NFTorrent.modelsbase import CollectionConfig
from NFTorrent.settings import Settings
from NFTorrent.tonlib import TonlibManager
from NFTorrent.utils import dict_to_influx, guess_type, parse_ipfs_uri

logger = logging.getLogger(__name__)


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

        if self.settings.indexdb.enabled:
            self.indexer = IndexDb(
                self.settings.indexdb,
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
                redundancy = len(ipfs_state["cluster_peers"]) >= self.settings.ipfs.min_redundancy
                stotage_state = ipfs_state["peers"] >= self.ipfs.settings.min_peers_count
        if self.indexer is not None:
            indexer_state = self.indexer.get_indexdb_state()
            last_checked = [x["fields"]["last_checked"] for x in indexer_state["stats"]]
            indexer_state = len(last_checked) == len(
                [x for x in last_checked if x >= time.time() - self.indexer.settings.indexer_timeout * 2]
            )

        return HealthCheckResult(
            tonlib=bool(tonlib_state),
            storage=bool(stotage_state),
            indexdb=bool(indexer_state),
            redundancy=bool(redundancy),
            load=round(load, 2),
        )

    def get_measurements(self, timestamp: int):
        hc = self.get_healthcheck()
        _stats = hc.dict()
        _stats["start_time"] = self.start_time
        measurements = [f"NFTorrentServer {dict_to_influx(_stats)} {timestamp}"]
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
                    headers={},
                )

        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content

        uri = nft_content.uri() if query == "uri" else nft_content.image()
        if uri:
            if uri.startswith("ipfs://"):
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
            return StreamingResponse(
                io.BytesIO(nft_content.image_data()),
                media_type="image/webp",
                headers={
                    "Content-Disposition": f'inline; filename="{address}.webp"',
                },
            )
        if query == "uri":
            return JSONResponse({"attributes": nft_content.metadata_attributes()})

        # TODO: Generate dynamic default image with pets Name
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    async def get_nft_torrent_content(self, address: str = None, file_path: str = None, digest: str = None):
        nft_data = await self.tonlib.get_nft_data(address)
        nft_content = nft_data.individual_content
        if nft_content is not None:
            image = nft_content.image()
            if image.startswith("ipfs://"):
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

    async def sync_nft_data(self, address: str = None, owner: str = None):
        nft_data = await self.tonlib.get_nft_data(address, owner=owner)
        nft_content = nft_data.individual_content
        if nft_content is not None:
            image = nft_content.image()
            if image and image.startswith("ipfs://"):
                cid, _, _ = parse_ipfs_uri(image)
                cid_info = await self.ipfs.get_cid_info(cid=cid, with_pin=True)
                if nft_content.storage_due_time() > (cid_info.pin.expires if cid_info.pin else time.time()):
                    self.loop.create_task(self.ipfs.confirm_content(address, old_cid=None, cid=cid))
            # TODO: Update IndexDB

    async def get_nft_cid_info(self, address: str, digest: str = None):
        cid, _ = await self.ipfs.get_nft_cid(address, raise_error=True)
        if digest and digest != torrent_digest(cid):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        response = await self.ipfs.get_cid_info(cid=cid)
        if digest and response.state == NftContentState.READY:
            return JSONResponse(jsonable_encoder(response), headers={
                "Cache-Control": "public, max-age=864000, immutable",
                "ETag": response.hash
            })

        return JSONResponse(jsonable_encoder(response))

    async def get_nft_cid_pin(self, address: str, digest: str = None):
        cid, _ = await self.ipfs.get_nft_cid(address, raise_error=True)
        if digest and digest != torrent_digest(cid):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        _pin = await self.ipfs.cid_pin_status(cid)
        if _pin["metadata"] and _pin["metadata"]["nft"]:
            return NftContentPin(
                redundancy=len(_pin["allocations"]),
                expires=float(_pin["metadata"].get("expires", "0")),
                created=time.mktime(time.strptime(_pin["created"], "%Y-%m-%dT%H:%M:%SZ")),
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)