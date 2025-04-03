import base64
from typing import Optional, List
from enum import IntEnum
from pydantic import BaseModel, validator
from fastapi.params import Path, File
from fastapi import UploadFile

from pytonlib.utils.address import prepare_address
from NFTorrent.address import parse_bag_id, parse_adnl_id


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
        except:
            raise ValueError('Ivalid TON contract address format')


class NftStorageTorrentMethod(NftMethod):
    file_path: str = Path(description="Torrent file path")


class NftTorrentCreate(NftMethod):
    files: List[UploadFile] = File(description="Torrent files")


class CHAIN(IntEnum):
    MAINNET = '-239'
    TESTNET = '-3'


class Account(BaseModel):
    address: str
    chain: CHAIN
    public_key: str

    @validator('address')
    def validate_contract_address(cls, v):
        try:
            return prepare_address(v)
        except:
            raise ValueError('Ivalid TON contract address format')


class HealthCheckResult(BaseModel):
    tonlib: bool
    storage: bool


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