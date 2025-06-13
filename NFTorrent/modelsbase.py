import abc
import datetime
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any

from pytonlib.utils.address import detect_address
from sqlmodel import Field, SQLModel
from tonpy.types import CellSlice

from NFTorrent.utils import dataclass_to_influx


@dataclass(frozen=True)
class TonAddress:
    address: str
    raw_form: str = field(init=False)
    b64: str = field(init=False)
    b64url: str = field(init=False)

    def __post_init__(self):
        address = detect_address(self.address)
        object.__setattr__(self, "raw_form", address["raw_form"])
        addr_map = None
        if "non_bounceable" in address["given_type"]:
            addr_map = address["non_bounceable"]
        else:
            addr_map = address["bounceable"]
        object.__setattr__(self, "b64", addr_map["b64"])
        object.__setattr__(self, "b64url", addr_map["b64url"])

    def __eq__(self, other):
        return self.raw_form == other.raw_form


@dataclass(frozen=True)
class StatisticNoTags:
    pass


@dataclass
class StatisticMeasurement:
    count: int = 0
    error: int = 0
    duration: float = 0

    def __enter__(self):
        self._st = time.perf_counter()
        self.count += 1

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            self.error += 1
        self.duration += time.perf_counter() - self._st


class MeasurementStore(defaultdict):

    def __init__(self, name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name

    def get_timestamp(self):
        return int(time.time() * 1000000000)

    def as_list(self):
        _timestamp = self.get_timestamp()
        return [{"tags": asdict(k), "fields": asdict(v), "timestamp": _timestamp} for k, v in self.items()]

    def as_influx(self, timestamp):
        timestamp = timestamp or self.get_timestamp()
        return [f"{self.name},{dataclass_to_influx(k)} {dataclass_to_influx(v)} {timestamp}" for k, v in self.items()]


class BaseCollectionModel(SQLModel, table=False):
    id: int = Field(default=None, primary_key=True)
    address: str = Field(unique=True, max_length=48)
    index: int = Field()


class BaseNftModel(SQLModel, table=False):
    id: int = Field(default=None, primary_key=True)
    collection_id: int = Field()
    address: str = Field(unique=True, max_length=48)
    index: int = Field(index=True)
    image: str | None = Field(default=None, max_length=256)
    image_data: bytes | None = Field(default=None)
    icons: bytes | None = Field(default=None)
    error_time: datetime.datetime | None = Field(default=None, index=True)
    error_code: str | None = Field(default=None, max_length=40)

    @classmethod
    @abc.abstractmethod
    def from_nftmodel(cls, collection: int, data: Any):
        pass

    @abc.abstractmethod
    def to_nftheader(self, collection_address: str, icon_size: str = None):
        pass


@dataclass
class BaseNftContent:

    @classmethod
    @abc.abstractmethod
    def from_tvm(cls, cs: CellSlice):
        pass

    @abc.abstractmethod
    def uri(self) -> str:
        pass

    @abc.abstractmethod
    def image(self) -> str:
        pass

    @abc.abstractmethod
    def image_data(self) -> bytes:
        pass

    @abc.abstractmethod
    def storage_due_time(self) -> int:
        pass


@dataclass
class BaseCollectionInfo:

    @classmethod
    @abc.abstractmethod
    def from_tvm(cls, stack: list):
        pass


@dataclass(frozen=True)
class CollectionInstance(TonAddress):
    image: str
    meta: dict[str, Any] = field(default_factory=dict)
    nft_samples: dict[str, str] = None


@dataclass
class CollectionConfig:
    collection_info_class: type[BaseCollectionInfo]
    nft_content_class: type[BaseNftContent]
    collections: list[CollectionInstance]
    dbmodel_class: type[BaseCollectionModel] = None
    dbmodel_nft_class: type[BaseNftModel] = None

    def __post_init__(self):
        self._collections_map = {x.raw_form: x for x in self.collections}

    def get_collection(self, address: str):
        return self._collections_map.get(TonAddress(address).raw_form)


@dataclass(frozen=True)
class CollectionData:
    address: str
    owner_address: str
    next_item_index: int
    collection_content: Any = None
    collection_info: BaseCollectionInfo = None


@dataclass(frozen=True)
class NftItemData:
    address: str
    init: bool
    index: int
    owner_address: str
    collection_address: str = None
    individual_content: BaseNftContent = None


@dataclass(frozen=True)
class NftItemHeader:
    address: str
    index: int
    owner_address: str
    collection_address: str = None
    image: str = None
    image_data: str = None
    icons: dict[str, list[str]] = None
