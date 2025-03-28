from typing import Optional, List
from pydantic import BaseModel, validator
from fastapi.params import Path, File
from fastapi import UploadFile

from pytonlib.utils.address import prepare_address
from NFTorrent.storage import parse_bag_id

class ProblemDetail(BaseModel):
    type: Optional[str] = None
    title: Optional[str] = None
    detail: Optional[str] = None
    status: Optional[int] = None
    errors: Optional[List] = None


class TorrentMethod(BaseModel):
    bag_id: str = Path(description="Torrent bag id")

    @validator('bag_id')
    def validate_contract_address(cls, v):
        return parse_bag_id(v)


class NftMethod(BaseModel):
    address: str = Path(description="Address of NFT item")

    @validator('address')
    def validate_contract_address(cls, v):
        try:
            return prepare_address(v)
        except:
            raise ValueError('Ivalid TON contract address format')


class NftTorrentMethod(NftMethod):
    file_path: str = Path(description="Torrent file path")


class NftTorrentCreate(NftMethod):
    files: List[UploadFile] = File(description="Torrent files")
