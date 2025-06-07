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


class NftContentMethod(NftMethod):
    q: str = Query(description="NFT content query", default=None)


class BaseNftContentMethod(BaseModel):
    address: str = Path(description="Address of NFT item")
    digest: str = Path(description="Content digest")

    @validator("address")
    def validate_contract_address(cls, v):
        try:
            return TonAddress(v).b64url
        except Exception as E:
            raise ValueError("Ivalid TON contract address format") from E


class NftStorageTorrentMethod(NftMethod):
    file_path: str = Path(description="Torrent file path")


class NftTorrentCreate(NftMethod):
    files: list[UploadFile] = File(description="Torrent files")


class NewNftTorrentCreate(BaseModel):
    files: list[UploadFile] = File(description="Torrent files")


class LiteserverId(BaseModel):
    _type: str = Field(..., alias="@type")
    key: str


class TonlibWorkerState(BaseModel):
    ls_index: int
    ip: int
    port: int
    provided: str | None
    id: LiteserverId
    is_working: bool
    is_archival: bool
    is_enabled: bool
    last_block: int
    restart_count: int
    tasks_count: int


class IndexDbWorkerState(BaseModel):
    address: str
    next_index: int
    stats: dict[str, int]


class TonlibManagerState(BaseModel):
    workers: dict[str, TonlibWorkerState]
    stats: dict[str, int]


class IndexDbState(BaseModel):
    collections: dict[str, IndexDbWorkerState]


class StorageWorkerState(BaseModel):
    client_id: int
    is_healthy: bool
    is_enabled: bool
    start_time: float
    restart_count: int
    tasks_count: int
    pending_tasks: int


class StorageManagerState(BaseModel):
    workers: dict[str, StorageWorkerState]
    stats: dict[str, int]
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
    load: float
    redundancy: bool
    tonlib: bool | None
    storage: bool | None
    indexdb: bool | None


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


class NftItemHeader(BaseModel):
    address: str
    index: int
    owner_address: str
    collection_address: str = None
    image: str = None
    image_data: str = None
    icons: dict[str, list[str]] = None


class CollectionItemsMethod(BaseModel):
    lang: str = Query(default=None)
    country: str = Query(default=None)
    species: str = Query(default=None)
    limit: int = Query(default=100)
    offset: int = Query(default=0)
    icon_size: str = Query(default="small")


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


class NftContentInfo(BaseModel):
    hash: str
    size: int
    state: NftContentState = NftContentState.READY
    digest: str = None
    files: list[NftContentFile]
    pin: NftContentPin = None

    def make_digest(self):
        digest = hashlib.shake_256((self.hash).encode()).digest(15)
        self.digest = base64.b32encode(digest).decode().lower()
        for f in self.files:
            digest = hashlib.shake_256((self.hash + f.name).encode()).digest(15)
            f.digest = base64.b32encode(digest).decode().lower()

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
