import abc
from dataclasses import dataclass
from typing import Any, Dict, List, Type

from pytonlib.utils.address import detect_address
from sqlmodel import Field, SQLModel
from tonpy.types import CellSlice


class BaseCollectionModel(SQLModel, table=False):
    id: int = Field(default=None, primary_key=True)
    address: str = Field(unique=True, max_length=48)
    index: int = Field()


class BaseNftModel(SQLModel, table=False):
    id: int = Field(default=None, primary_key=True)
    collection_id: int = Field()
    address: str = Field(unique=True, max_length=48)
    index: int = Field(index=True)

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
    def bag_id(self):
        pass

    @abc.abstractmethod
    def image(self):
        pass

    @abc.abstractmethod
    def image_data(self):
        pass

    @abc.abstractmethod
    def storage_due_time(self):
        pass


@dataclass
class BaseCollectionInfo:

    @classmethod
    @abc.abstractmethod
    def from_tvm(cls, stack: List):
        pass


@dataclass(frozen=True)
class CollectionInstance:
    address: str
    image: str
    # _address: Dict[str, Any] = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "_address", detect_address(self.address))

    def address_url(self):
        return self._address['bounceable']['b64url']


@dataclass
class CollectionConfig:
    collection_info_class: Type[BaseCollectionInfo]
    nft_content_class: Type[BaseNftContent]
    collections: List[CollectionInstance]
    dbmodel_class: Type[BaseCollectionModel] = None
    dbmodel_nft_class: Type[BaseNftModel] = None

    def __post_init__(self):
        self._collections_map = {
            x._address['raw_form']: x
            for x in self.collections
        }

    def get_collection(self, address: str):
        return self._collections_map.get(detect_address(address)['raw_form'])


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
    icons: Dict[str, List[str]] = None
