import abc
from enum import IntEnum
from typing import Dict, List, Optional

from fastapi import UploadFile
from fastapi.params import File, Path
from pydantic import BaseModel, Field, validator
from pytonlib.utils.address import detect_address, prepare_address

from NFTorrent.address import parse_adnl_id, parse_bag_id


class TvmStructure:
    pass


class NftContent(TvmStructure):

    @abc.abstractmethod
    def bag_id(self):
        pass

    @abc.abstractmethod
    def image(self):
        pass

    @abc.abstractmethod
    def image_data(self):
        pass


class NftCollection:

    def __init__(self, nft_content_class: NftContent, address: str, image: str = None):
        self.nft_content_class = nft_content_class
        self.address = prepare_address(address)
        self.raw_address = detect_address(self.address)['raw_form']
        self.image = image

    @property
    def ntf_content(self):
        return self.nft_content_class.__name__


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


class NftContentMethod(BaseModel):
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


class TonlibManagerState(BaseModel):
    liteservers: Dict[str, TonlibWorkerState]


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
    tonlib: bool
    storage: bool
    redundancy: bool
    load: float


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
