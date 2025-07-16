import abc
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from functools import wraps
from typing import Any

from pytonlib.utils.address import detect_address
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
        addr_map = address["bounceable"]
        object.__setattr__(self, "b64", addr_map["b64"])
        object.__setattr__(self, "b64url", addr_map["b64url"])

    def __eq__(self, other):
        return self.raw_form == other.raw_form


@dataclass(frozen=True)
class BaseStatisticTags:
    pass


@dataclass(frozen=True)
class StatisticNoTags(BaseStatisticTags):
    pass


@dataclass(frozen=True)
class MethodStatisticTags(BaseStatisticTags):
    method: str


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

    def __init__(self, name: str, *args, default_tag_factory: type[BaseStatisticTags] = MethodStatisticTags, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name
        self.default_tag_factory = default_tag_factory

    def get_timestamp(self):
        return int(time.time() * 1000000000)

    def as_list(self):
        _timestamp = self.get_timestamp()
        return [{"measurement": self.name, "tags": asdict(k if is_dataclass(k) else self.default_tag_factory(k)), "fields": asdict(v), "timestamp": _timestamp} for k, v in self.items()]

    def as_influx(self, timestamp):
        timestamp = timestamp or self.get_timestamp()
        return sorted([f"{self.name},{dataclass_to_influx(k if is_dataclass(k) else self.default_tag_factory(k))} {dataclass_to_influx(v)} {timestamp}" for k, v in self.items()])


def with_stats(key: Any = None, stats: MeasurementStore = None, stats_attr: str = "stats"):
    def decorator(method):
        @wraps(method)
        async def wrapper(*args, **kwargs):
            if stats is not None:
                container = stats
            else:
                container = getattr(args[0], stats_attr)

            with container[key or method.__name__]:
                return await method(*args, **kwargs)
        return wrapper
    return decorator


@dataclass
class BaseNftContent(abc.ABC):

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

    @abc.abstractmethod
    def title(self) -> str:
        pass

    @abc.abstractmethod
    def subtitle(self) -> str:
        pass

    @abc.abstractmethod
    def metadata_attributes(self) -> dict[str, Any]:
        pass



@dataclass
class BaseCollectionInfo(abc.ABC):

    @classmethod
    @abc.abstractmethod
    def from_tvm(cls, stack: list):
        pass


@dataclass(frozen=True)
class CollectionItemCover:
    baseimage_path: str
    font: str
    subtitle_font: str = None
    title_size: int = 96
    subtitle_size: int = 48
    offset_top: float = 0.875
    color: Any = "black"
    rect_fill: Any = "white"
    rect_padding: tuple[int, int] = (64, 8)
    rect_margin: tuple[int, int] = (24, 0)


@dataclass(frozen=True)
class CollectionInstance(TonAddress):
    image: str
    item_cover: CollectionItemCover = None
    meta: dict[str, Any] = field(default_factory=dict)
    nft_samples: dict[str, str] = None


@dataclass
class CollectionConfig:
    collection_info_class: type[BaseCollectionInfo]
    nft_content_class: type[BaseNftContent]
    collections: list[CollectionInstance]

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
    torrent_digest: str | None = None


@dataclass(frozen=True)
class NftItemHeader:
    name: str
    address: str
    index: int
    owner_address: str
    collection_address: str = None
    image: str = None
    icons: dict[str, list[str]] = None
    deleted: bool = False
