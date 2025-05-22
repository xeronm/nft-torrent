import hashlib
import base64
from enum import IntEnum, Enum
from typing import Any, Dict, List, Optional

from fastapi import UploadFile
from fastapi.params import File, Path, Query
from pydantic import BaseModel, Field, validator
from pytonlib.utils.address import prepare_address

from NFTorrent.blockchain.address import parse_adnl_id, parse_bag_id


class ProblemDetail(BaseModel):
    type: Optional[str] = None
    title: Optional[str] = None
    detail: Optional[str] = None
    status: Optional[int] = None
    errors: Optional[List] = None


class StorageTorrentMethod(BaseModel):
    bag_id: str = Path(description="Torrent bag id")

    @validator('bag_id')
    def validate_contract_address(cls, v):
        return parse_bag_id(v)


class StorageTorrentContentMethod(BaseModel):
    bag_id: str = Path(description="Torrent bag id")
    digest: str = Path(description="Content digest")

    @validator('bag_id')
    def validate_contract_address(cls, v):
        return parse_bag_id(v)


class StoragePeerMethod(BaseModel):
    adnl_id: str = Path(description="ADNL id")

    @validator('adnl_id')
    def validate_adnl_address(cls, v):
        return parse_adnl_id(v)


class NftMethod(BaseModel):
    address: str = Path(description="Address of NFT item")

    @validator('address')
    def validate_contract_address(cls, v):
        try:
            return prepare_address(v)
        except Exception:
            raise ValueError('Ivalid TON contract address format')

class NftContentMethod(NftMethod):
    q: str = Query(description="NFT content query", default=None)


class BaseNftContentMethod(BaseModel):
    address: str = Path(description="Address of NFT item")
    digest: str = Path(description="Content digest")

    @validator('address')
    def validate_contract_address(cls, v):
        try:
            return prepare_address(v)
        except Exception:
            raise ValueError('Ivalid TON contract address format')


class NftStorageTorrentMethod(NftMethod):
    file_path: str = Path(description="Torrent file path")


class NftTorrentCreate(NftMethod):
    files: List[UploadFile] = File(description="Torrent files")


class LiteserverId(BaseModel):
    _type: str = Field(..., alias="@type")
    key: str


class TonlibWorkerState(BaseModel):
    ls_index: int
    ip: int
    port: int
    provided: Optional[str]
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
    stats: Dict[str, int]


class TonlibManagerState(BaseModel):
    workers: Dict[str, TonlibWorkerState]
    stats: Dict[str, int]


class IndexDbState(BaseModel):
    collections: Dict[str, IndexDbWorkerState]


class StorageWorkerState(BaseModel):
    client_id: int
    is_healthy: bool
    is_enabled: bool
    start_time: float
    restart_count: int
    tasks_count: int
    pending_tasks: int


class StorageManagerState(BaseModel):
    workers: Dict[str, StorageWorkerState]
    stats: Dict[str, int]
    size: int
    size_pressure: int


class NodePeerInfo(BaseModel):
    adnl_id: str = Field(..., description='Raw ADNL id address (decoded) form')
    ip_str: str = Field(..., description='IP address an port of TON Storage server')
    adnl: str = Field(..., description='User-friendly ADNL address (encoded) form')


class CHAIN(IntEnum):
    MAINNET = -239
    TESTNET = -3


class Account(BaseModel):
    address: str
    chain: Optional[CHAIN] = None
    public_key: str

    @validator('address')
    def validate_contract_address(cls, v):
        try:
            return prepare_address(v)
        except Exception:
            raise ValueError('Ivalid TON contract address format')


class HealthCheckResult(BaseModel):
    load: float
    redundancy: bool
    tonlib: Optional[bool]
    storage: Optional[bool]
    indexdb: Optional[bool]


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
    aud: List[str]
    exp: int


class AuthSession(BaseModel):
    node: HealthCheckResult
    sess: Optional[JWTPayload]


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
    icons: Dict[str, List[str]] = None


class CollectionItemsMethod(BaseModel):
    lang: str = Query(default=None)
    country: str = Query(default=None)
    species: str = Query(default=None)
    limit: int = Query(default=100)
    offset: int = Query(default=0)
    icon_size: str = Query(default='small')


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
    files: List[NftContentFile]
    pin: NftContentPin = None

    def make_digest(self):
        for f in self.files:
            digest = hashlib.shake_256((self.hash + f.name).encode()).digest(15)
            f.digest = base64.b32encode(digest).decode().lower()


class IpfsNodeStorageState(BaseModel):
    RepoSize: int
    StorageMax: int
    NumObjects: int = None


class IpfsNodeState(BaseModel):
    storage: IpfsNodeStorageState
    peers: str = None

