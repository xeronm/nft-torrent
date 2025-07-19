import asyncio
import datetime
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode, urljoin
from dataclasses import dataclass

import aiohttp
from dateutil.parser import isoparse
from fastapi import HTTPException, UploadFile, status

from NFTorrent import exceptions, models
from NFTorrent.cache import BaseCacheManager, DisabledCacheManager
from NFTorrent.modelsbase import MeasurementStore, StatisticMeasurement, StatisticNoTags, with_stats
from NFTorrent.settings import IpfsSettings
from NFTorrent.tonlib import TonlibManager
from NFTorrent.utils import dict_to_influx, parse_ipfs_uri

logger = logging.getLogger(__name__)


class LockShouldWaitError(Exception):
    pass


class OperationLock:

    def __init__(self, key: str, lock_index: dict[str, asyncio.Lock], wait: bool = True):
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
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.lock.release()
        self.lock.__ref_count -= 1
        if self.lock.__ref_count == 0:
            del self.lock_index[self.key]
        self.lock = None


class IpfsRpcHttpException(HTTPException):

    def __str__(self):
        return f"status={self.status_code}, detail={self.detail}"


class IpfsRpcManager:
    node_state_cache_timeout = 60
    node_state_restart_timeout = 30
    node_state_check_timeout = 5

    def __init__(
        self,
        settings: IpfsSettings,
        #  num_workers: int = None,
        #  restart_timeout: int = None,
        cache_manager: BaseCacheManager | None = None,
        loop: asyncio.BaseEventLoop | None = None,
        tonlib: TonlibManager = None,
    ):
        self.settings = settings
        self.cache_manager = cache_manager or DisabledCacheManager()
        self.tonlib = tonlib
        self.loop = loop
        self.node_state = None

        self.cid_wlock = {}
        self.tasks = {
            "check_ipfs_alive": self.loop.create_task(self.check_ipfs_alive()),
        }
        self.stats = MeasurementStore("NFTorrentIpfsHTTPClient", StatisticMeasurement)

        # cache setup
        self.setup_cache()
        self.client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout),
            base_url=urljoin(self.settings.kubo_rpc_uri + "/", "api/v0/"),
        )
        self.cluster = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.request_timeout), base_url=self.settings.cluster_rpc_uri
        )

    async def shutdown(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.wait(self.tasks.values())
        self.client.close()
        self.cluster.close()

    def setup_cache(self):
        self.get_cid_file = with_stats(key="cached_get_cid_file", stats=self.stats)(
            self.cache_manager.cached(expire=15)(self.get_cid_file)
        )
        self.get_cid_info = with_stats(key="cached_get_cid_info", stats=self.stats)(
            self.cache_manager.cached(expire=60)(self.get_cid_info)
        )
        self.cid_pin_status = with_stats(key="cached_cid_pin_status", stats=self.stats)(
            self.cache_manager.cached(expire=30)(self.cid_pin_status)
        )

    async def check_ipfs_alive(self):
        logger.warning("[check_ipfs_alive]: Entering main loop")
        while True:
            try:
                try:
                    await self.get_node_state()
                except Exception as E:
                    logger.warning(
                        "[check_ipfs_alive]: Failed to get node state - %s: %s",
                        type(E),
                        E,
                    )

                await asyncio.sleep(self.node_state_check_timeout)
            except asyncio.CancelledError:
                logger.info("[check_ipfs_alive]: Task was cancelled")
                return
            except (Exception, BaseException):
                logger.exception(
                    "[check_ipfs_alive]: Unhandled exception, sleep for %d sec",
                    self.node_state_restart_timeout,
                )
                await asyncio.sleep(self.node_state_restart_timeout)

    async def get_nft_cid(
        self, address: str, skip_verification: bool = False, owner: str = None, raise_error: bool = False
    ):
        nft_data = await self.tonlib.get_nft_data(address, skip_verification, owner=owner)
        nft_content = nft_data.individual_content

        cid = None
        if nft_content is not None:
            image = nft_content.image()
            if image:
                cid, _, _ = parse_ipfs_uri(image)
        if raise_error and not cid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return cid, nft_content

    async def call_rpc_method(
        self,
        stat_name: str,
        method: type[aiohttp.ClientResponse],
        uri: str,
        json: bool = False,
        text: bool = False,
        data: Any = None,
    ):
        kwargs = {}
        if data is not None:
            kwargs["data"] = data
        with self.stats[stat_name]:
            try:
                logger.info('IPFS Call "%s: %s"', method.__name__.upper(), uri)
                result = None
                async with method(uri, **kwargs) as resp:
                    if resp.status != status.HTTP_200_OK:
                        raise IpfsRpcHttpException(status_code=resp.status, detail=await resp.text())
                    if json:
                        result = await resp.json()
                    elif text:
                        result = await resp.text()
                    else:
                        result = await resp.read()
                return result
            except (aiohttp.client_exceptions.ClientError, aiohttp.client_exceptions.ClientConnectorError) as E:
                logger.error(
                    'IPFS Call "%s: %s" got error - %s: %s',
                    method.__name__.upper(),
                    uri,
                    type(E).__name__,
                    E,
                )
                raise

    @with_stats()
    async def cid_add_local(self, files: list[UploadFile] = None) -> models.NftContentInfo:
        data = aiohttp.FormData()
        for f in files:
            data.add_field("files", await f.read(), filename=f.filename, content_type=f.content_type)
        uri = "add?recursive=true&wrap-with-directory=true&pin=false&cid-version=1"
        response = await self.call_rpc_method("cid_add", self.client.post, uri, data=data, text=True)
        content = None
        files = []
        for line in response.split("\n"):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item["Name"] == "":
                content = models.NftContentInfo(hash=item["Hash"], size=item["Size"], files=[])
            else:
                files.append(models.NftContentFile(name=item["Name"], size=item["Size"], hash=item["Hash"]))
        if content:
            content.files = files
            content.make_digest()
        return content

    @with_stats()
    async def cid_pin(
        self, cid: str = None, name: str = None, expire_at: float = None, address: str = None, userdata: Any = None
    ):
        name = name or ""
        if self.settings.cluster_rpc_uri:
            expire_at_str = (
                datetime.datetime.fromtimestamp(expire_at, tz=datetime.timezone.utc).isoformat() if expire_at else ""
            )
            query_params = {
                "mode": "recursive",
                "replication-min": self.settings.min_redundancy,
                "replication-max": self.settings.min_redundancy + 2,
            }
            if name:
                query_params["name"] = name
            if expire_at:
                query_params["expire-at"] = expire_at_str
                query_params["meta-expires"] = expire_at
            if address:
                query_params["meta-nft"] = address
            if userdata:
                query_params["meta-userdata"] = json.dumps(userdata, separators=(",", ":"))
            uri = f"/pins/{cid}?{urlencode(query_params)}"
            return await self.call_rpc_method("pin", self.cluster.post, uri, json=True)
        else:
            uri = f"pin/add?arg={cid}&recursive=true&name={name}"
            return await self.call_rpc_method("pin", self.cluster.post, uri, json=True)

    @with_stats()
    async def cid_unpin(self, cid: str = None):
        try:
            if self.settings.cluster_rpc_uri:
                uri = f"/pins/{cid}"
                return await self.call_rpc_method("unpin", self.cluster.delete, uri, json=True)
            else:
                uri = f"pin/rm?arg={cid}&recursive=true"
                return await self.call_rpc_method("unpin", self.cluster.post, uri, json=True)
        except IpfsRpcHttpException as E:
            if E.status_code != status.HTTP_404_NOT_FOUND:
                raise

    @with_stats()
    async def cid_pin_status(self, cid: str = None) -> models.NftContentPin:
        try:
            if self.settings.cluster_rpc_uri:
                uri = f"/pins/{cid}"
                pin_status = await self.call_rpc_method("pin_status", self.cluster.get, uri, json=True)
            else:
                uri = f"pin/ls?arg={cid}"
                pin_status = await self.call_rpc_method("pin_status", self.cluster.post, uri, json=True)

            if not pin_status["metadata"]:
                pin_status["metadata"] = {}
            userdata = pin_status["metadata"].get("userdata", None)
            if userdata:
                userdata = json.loads(userdata)

            return models.NftContentPin(
                redundancy=len(pin_status["allocations"]),
                expires=int(pin_status["metadata"].get("expires", "0")),
                created=int(isoparse(pin_status["created"]).timestamp()),
                nft_address=pin_status["metadata"].get("nft"),
                userdata=userdata,
            )
        except IpfsRpcHttpException as E:
            if E.status_code != status.HTTP_404_NOT_FOUND:
                raise
        return None

    @with_stats()
    async def pin_list(self) -> models.NftContentPin:
        allocations = await self.call_rpc_method("pin_list", self.cluster.get, "allocations", json=False, text=True)
        pins = []
        for item in allocations.split('\n'):
            item = item.strip()
            if not item:
                continue

            _item = json.loads(item)
            if not _item["metadata"]:
                _item["metadata"] = {}
            userdata = _item["metadata"].get("userdata", None)
            if userdata:
                userdata = json.loads(userdata)

            pins.append(
                models.NftContentPin(
                    redundancy=len(_item["allocations"]),
                    expires=int(_item["metadata"].get("expires", "0")),
                    created=int(isoparse(_item["timestamp"]).timestamp()),
                    nft_address=_item["metadata"].get("nft"),
                    cid=_item["cid"],
                    userdata=userdata,
                ))

        return pins

    @with_stats()
    async def confirm_content(self, address: str, old_cid: str, cid: str, userdata: Any = None):
        try:
            async with OperationLock(f"nft:{address}:pin", self.cid_wlock, wait=False):
                curr_time = st_time = time.monotonic()
                curr_cid = None
                while st_time + self.settings.confirmation_timeout > curr_time:
                    curr_cid, nft_content = await self.get_nft_cid(address)
                    if curr_cid == cid:
                        break
                    await asyncio.sleep(10)
                    curr_time = time.monotonic()

                async with OperationLock(f"cid:{cid}:pin", self.cid_wlock):
                    if curr_cid != cid:
                        raise TimeoutError()

                    logger.warning("Pin confirmed for CID, NFT: %s, cid: %s", address, cid)
                    await self.cid_pin(
                        cid,
                        name=address,
                        address=address,
                        expire_at=nft_content.storage_due_time(),
                        userdata=userdata,
                    )
                    if old_cid is not None:
                        await self.cid_unpin(old_cid)
        except Exception as E:
            logger.warning(
                "CID was not pinned, NFT: %s, cid: %s, curr_cid: %s due to error - %s: %s",  # noqa: E501
                address,
                cid,
                curr_cid,
                type(E).__name__,
                E,
            )

    def get_cached_node_state(self):
        return self.node_state

    async def get_node_state(self):
        curr_time = time.monotonic()
        if self.node_state is None or curr_time > self.node_state_time + self.node_state_cache_timeout:
            tasks = await asyncio.gather(
                self.call_rpc_method("repo_stat", self.client.post, "repo/stat", json=True),
                self.call_rpc_method("swarm_peers", self.client.post, "swarm/peers", json=True),
                self.call_rpc_method("metrics_ping", self.cluster.get, "monitor/metrics/ping", json=True),
            )
            self.node_state_time = curr_time
            self.node_state = {
                "storage": tasks[0],
                "peers": len(tasks[1]["Peers"]),
                "cluster_peers": tasks[2],
                "stats": self.stats.as_list(),
            }
        return self.node_state

    def get_measurements(self, timestamp: int) -> list[str]:
        state = self.get_cached_node_state()
        result = self.stats.as_influx(timestamp)
        if state is not None:
            _ipfs = {
                "peers": state["peers"],
                "cluster_peers": len(state["cluster_peers"]),
                "cluster_active_peers": len([x for x in state["cluster_peers"] if x["valid"]]),
                "size": state["storage"]["RepoSize"],
                "max_size": state["storage"]["StorageMax"],
                "objects": state["storage"].get("NumObjects"),
            }
            result += [f"NFTorrentIpfs {dict_to_influx(_ipfs)} {timestamp}"]
        return result

    @with_stats()
    async def get_cid_info(self, cid: str = None) -> models.NftContentInfo:
        _resp = await self.call_rpc_method("cid_ls", self.client.post, f"ls?arg={cid}", json=True)

        _content = _resp["Objects"][0]
        content = models.NftContentInfo(
            hash=_content["Hash"],
            size=0,
            files=[models.NftContentFile(name=x["Name"], size=x["Size"], hash=x["Hash"]) for x in _content["Links"]],
        )
        content.size = sum([x.size for x in content.files])
        content.make_digest()
        return content

    async def get_cid_file_info(self, uri: str = None, cid: str = None, file_path: str = None, digest: str = None):
        if uri:
            cid, _file_path, _digest = parse_ipfs_uri(uri)
            if file_path is None and digest is None:
                file_path, digest = _file_path, _digest
        if not cid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CID not defined")
        info = await self.get_cid_info(cid=cid)
        file_info = None
        if digest or file_path:
            file_info = info.get_file(filename=file_path, digest=digest)
        else:
            _list = info.list_types(mime_prefix="image/")
            if _list is not None:
                file_info = _list[0]
        if not file_info:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return file_info

    @with_stats()
    async def get_cid_file(
        self, uri: str = None, cid: str = None, file_path: str = None, digest: str = None
    ) -> tuple[bytes, models.NftContentInfo | models.NftContentFile]:
        if uri:
            cid, _file_path, _digest = parse_ipfs_uri(uri)
            if file_path is None and digest is None:
                file_path, digest = _file_path, _digest
        if not cid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CID not defined")
        info = await self.get_cid_info(cid=cid)
        file_info = None
        if info.files:
            file_info = info.get_file(filename=file_path, digest=digest)
        elif info.digest == digest or not digest:
            file_info = info
        if not file_info:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        if file_info.size > self.settings.file_size_limit:
            raise exceptions.TorrentSizeLimit(f"file size limit: {self.settings.file_size_limit}")

        if not info.files:
            data = await self.call_rpc_method("cid_cat", self.client.post, f"cat?arg={cid}")
        else:
            query_params = {"arg": f"{cid}/{file_info.name}"}
            data = await self.call_rpc_method("cid_cat", self.client.post, f"cat?{urlencode(query_params)}")
        return data, file_info

    # High-Level API
    @with_stats()
    async def new_nft_create_content(self, files: list[UploadFile], owner: str = None):
        total_size = sum([f.size for f in files])
        total_size = sum([f.size for f in files])
        if total_size > self.settings.cid_size_limit:
            raise exceptions.TorrentSizeLimit(f"total limit: {self.settings.cid_size_limit}")
        if [f.size for f in files if f.size > self.settings.file_size_limit]:
            raise exceptions.TorrentSizeLimit(f"file limit: {self.settings.file_size_limit}")
        logger.warning(
            "Creating CID for new NFT, owner: %s, size: %d",  # noqa: E501
            owner,
            total_size,
        )
        content = None
        try:
            async with OperationLock(f"owner:{owner}:new", self.cid_wlock, wait=False):
                content = await self.cid_add_local(files=files)
        except Exception as E:
            logger.warning(
                "Creating CID, for new NFT, owner: %s, size: %d failed with error - %s: %s",  # noqa: E501
                owner,
                total_size,
                type(E).__name__,
                E,
            )
            raise
        return content

    @with_stats()
    async def create_content(self, address: str, files: list[UploadFile], owner: str = None, userdata: Any = None):
        cid, nft_content = await self.get_nft_cid(address, owner=owner)

        total_size = sum([f.size for f in files])
        if total_size > self.settings.cid_size_limit:
            raise exceptions.TorrentSizeLimit(f"total limit: {self.settings.cid_size_limit}")
        if [f.size for f in files if f.size > self.settings.file_size_limit]:
            raise exceptions.TorrentSizeLimit(f"file limit: {self.settings.file_size_limit}")

        node_state = self.get_cached_node_state()
        cluster_peers = len(node_state["cluster_peers"])
        if cluster_peers < self.settings.min_redundancy:
            raise exceptions.TorrentStorageError(
                f"Unable to comply required redundancy, min={self.settings.min_redundancy}, peers={cluster_peers}"
            )

        logger.warning(
            "Creating CID, NFT: %s, curr_cid: %s, size: %d",  # noqa: E501
            address,
            cid,
            total_size,
        )
        try:
            async with OperationLock(f"nft:{address}:add", self.cid_wlock, wait=False):
                content = await self.cid_add_local(files=files)
                new_cid = content.hash

                if cid != new_cid:
                    logger.info(
                        "Waiting for confirmation created CID, NFT: %s, new cid: %s",  # noqa: E501
                        address,
                        new_cid,
                    )
                    self.loop.create_task(self.confirm_content(address, cid, new_cid, userdata=userdata))
                else:
                    logger.warning(
                        "Created CID has already been confirmed, NFT: %s, cid: %s",
                        address,
                        new_cid,
                    )
                    await self.cid_pin(
                        new_cid, name=address, expire_at=nft_content.storage_due_time(), userdata=userdata
                    )
        except Exception as E:
            logger.warning(
                "Creating CID, NFT: %s, size: %d - failed with error - %s: %s",  # noqa: E501
                address,
                total_size,
                type(E).__name__,
                E,
            )
            raise

        return content

    @with_stats()
    async def nft_unlink(self, cid: str, address: str):
        pin = await self.cid_pin_status(cid)
        if pin and pin.nft_address == address:
            await self.cid_unpin(cid)

