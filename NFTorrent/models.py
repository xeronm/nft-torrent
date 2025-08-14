import base64
import hashlib
from enum import Enum, IntEnum
from typing import Any

from fastapi import UploadFile
from fastapi.params import File, Path, Query
from pydantic import BaseModel, Field, validator

from NFTorrent.modelsbase import TonAddress
from NFTorrent.utils import guess_type


class ProblemDetail(BaseModel):
    type: str | None = None
    title: str | None = None
    detail: str | None = None
    status: int | None = None
    errors: list | None = None


class NftMethod(BaseModel):
    address: str = Path(description="Address of NFT item")

    @validator("address")
    def validate_contract_address(cls, v):
        try:
            return TonAddress(v).b64url
        except Exception as E:
            raise ValueError("Ivalid TON contract address format") from E


class IpfsCidMethod(BaseModel):
    cid: str = Path(description="IPFS CID")


class NftContentMethod(NftMethod):
    q: str | None = Query(description="NFT content query", default=None)


class BaseNftContentMethod(NftMethod):
    digest: str = Path(description="Content digest")


class NftStorageTorrentMethod(NftMethod):
    file_path: str = Path(description="Torrent file path")


class NftTorrentCreate(NftMethod):
    files: list[UploadFile] = File(description="Torrent files")


class NewNftTorrentCreate(BaseModel):
    files: list[UploadFile] = File(description="Torrent files")


class LiteserverId(BaseModel):
    type: str = Field(..., alias="@type")
    key: str


class TonlibWorkerState(BaseModel):
    ls_index: int = 0
    ls_config: dict[str, Any] = None
    is_alive: bool = False
    is_sync: bool = False
    is_enabled: bool = True
    is_archival: bool = False
    last_block: int = -1
    last_block_time: float = 0
    start_mt: float = 0
    start_time: float = 0
    restart_count: int = 0
    tasks_count: int = 0
    pending_tasks: int = 0
    sync_time: float = 0
    sync_mt: float = 0
    sync_duration: float = 0
    sync_dur_ema: float = 0
    off_sync_time: float = 0
    off_sync_mt: float = 0
    off_sync_count: int = 0
    off_sync_duration: float = 0
    off_sync_dur_ema: float = 0


class MeasurementItem(BaseModel):
    measurement: str | None
    tags: dict[str, Any] | None
    fields: dict[str, Any]
    timestamp: int


class TonlibManagerState(BaseModel):
    workers: dict[int, TonlibWorkerState]
    stats: list[MeasurementItem]


class IndexDbState(BaseModel):
    collections: list[Any]
    stats: list[MeasurementItem]


class StorageWorkerState(BaseModel):
    client_id: int
    is_sync: bool
    is_enabled: bool
    start_time: float
    restart_count: int
    tasks_count: int
    pending_tasks: int


class StorageManagerState(BaseModel):
    workers: dict[int, StorageWorkerState]
    stats: list[MeasurementItem]
    size: int
    size_pressure: int


class NodePeerInfo(BaseModel):
    adnl_id: str = Field(..., description="Raw ADNL id address (decoded) form")
    ip_str: str = Field(..., description="IP address an port of TON Storage server")
    adnl: str = Field(..., description="User-friendly ADNL address (encoded) form")


class CHAIN(IntEnum):
    MAINNET = -239
    TESTNET = -3


class Account(BaseModel):
    address: str
    chain: CHAIN | None = None
    public_key: str

    @validator("address")
    def validate_contract_address(cls, v):
        try:
            return TonAddress(v).b64url
        except Exception as E:
            raise ValueError("Ivalid TON contract address format") from E


class HealthCheckResult(BaseModel):
    node_id: str
    load: float
    redundancy: float
    tonlib: bool | None
    storage: bool | None
    indexdb: bool | None
    bot: bool | None


class TonProof(BaseModel):
    timestamp: int
    domain: str
    payload: str
    signature: str


class AuthPayload(BaseModel):
    payload: str


class AuthData(BaseModel):
    account: Account
    proof: TonProof


class JWTPayload(BaseModel):
    sub: str
    aud: list[str]
    exp: int
    user: Any = None


class AuthSession(BaseModel):
    node: HealthCheckResult
    sess: JWTPayload | None


class CollectionData(BaseModel):
    address: str
    owner_address: str
    next_item_index: int
    collection_content: Any = None
    collection_info: Any = None


class NftItemData(BaseModel):
    address: str
    init: bool
    index: int
    owner_address: str
    collection_address: str = None
    individual_content: Any = None
    torrent_digest: str | None = None


class NftItemContent(BaseModel):
    name: str
    image: str | None = None
    image_data: str | None = None

class NftItemHeader(BaseModel):
    address: str
    index: int
    owner_address: str
    collection_address: str | None = None
    content: NftItemContent
    icons: dict[str, list[str]] | None = None
    deleted: bool | None = False


class CollectionItemsMethod(BaseModel):
    lang: str | None = Query(default=None)
    country: str | None = Query(default=None)
    owner: str | None = Query(default=None)
    species: int | None = Query(default=None)
    limit: int = Query(default=100)
    offset: int = Query(default=0)
    icon_size: str = Query(default="small")

    @validator("owner")
    def validate_contract_address(cls, v):
        if not v:
            return None
        try:
            return TonAddress(v).b64url
        except Exception as E:
            raise ValueError("Ivalid TON contract address format") from E


class NftListMethod(BaseModel):
    limit: int = Query(default=20)
    offset: int = Query(default=0)
    icon_size: str = Query(default="medium")


class NftContentState(Enum):
    READY = 1
    ERROR = 2


class NftContentFile(BaseModel):
    name: str
    size: int
    hash: str = None
    state: NftContentState = NftContentState.READY
    digest: str = None


class NftContentPin(BaseModel):
    redundancy: int
    created: int = None
    expires: int = None
    userdata: Any | None = None
    cid: str | None = None
    nft_address: str | None = None


def torrent_digest(hash: str, filename: str = None) -> str:
    if filename:
        hash += filename
    digest = hashlib.shake_256(hash.encode()).digest(15)
    return base64.b32encode(digest).decode().lower()


class NftContentInfo(BaseModel):
    hash: str
    size: int
    state: NftContentState = NftContentState.READY
    digest: str = None
    files: list[NftContentFile] = None

    def make_digest(self):
        self.digest = torrent_digest(self.hash)
        for f in self.files:
            f.digest = torrent_digest(self.hash, f.name)

    def get_file(self, filename: str = None, digest: str = None):
        for info in self.files:
            if info.name == filename or info.digest == digest:
                return info
        return None

    def list_types(self, mime_prefix: str = None):
        return [
            info
            for info in self.files
            if not info.name.startswith(".") and (guess_type(info.name)[0] or "").startswith(mime_prefix)
        ]

    @property
    def name(self):
        return self.hash


class IpfsNodeStorageState(BaseModel):
    RepoSize: int
    StorageMax: int
    NumObjects: int = None


class IpfsNodeState(BaseModel):
    storage: IpfsNodeStorageState
    peers: int = None
    cluster_peers: Any = None
