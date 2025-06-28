import base64
import datetime
import enum
import pickle

from sqlmodel import Field, SQLModel, UniqueConstraint

from .blockchain.models import GeoPoint, NftMutableMetaData, PetMemoryNftContent, PetMemoryNftImmutableData
from .modelsbase import NftItemData, NftItemHeader


class PetsCollection(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    address: str = Field(unique=True, max_length=48)
    index: int = Field()
    updated_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    __tablename__ = "pets_collection"


class PetMemoryNft(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    collection_id: int = Field(foreign_key="pets_collection.id")
    address: str = Field(unique=True, max_length=48)
    index: int = Field(index=True)
    created_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    updated_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    last_notified: datetime.datetime | None = Field(default=None)
    # Immutable Data
    lang: str = Field(index=True, max_length=2)
    name: str = Field(max_length=100)
    sex: int = Field()
    species: int = Field(index=True)
    species_name: str | None = Field(default=None)
    breed: str | None = Field(default=None)
    country: str = Field(default=None, index=True, max_length=2)
    geo_point_is_south: bool | None = Field(default=None)
    geo_point_latitude: float | None = Field(default=None)
    geo_point_longitude: float | None = Field(default=None)
    location: str | None = Field(default=None, max_length=100)
    birth_date: str | None = Field(default=None)
    death_date: str | None = Field(default=None)
    # Mutable Data
    owner: str = Field(index=True, max_length=48)
    fee_due_time: int = Field()
    uri: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    image: str | None = Field(default=None, max_length=500)
    image_data: bytes | None = Field(default=None)
    #
    icons: bytes | None = Field(default=None)
    error_time: datetime.datetime | None = Field(default=None, index=True)
    error_code: str | None = Field(default=None, max_length=40)

    __tablename__ = "pet_memory_nft"
    __table_args__ = (UniqueConstraint("collection_id", "index", name="collection_index_uk"),)

    @classmethod
    def from_nftmodel(cls, collection_id: int, data: NftItemData):
        if not isinstance(data.individual_content, PetMemoryNftContent):
            raise ValueError(
                f'invalid individual_content type="{type(data.individual_content)}", PetMemoryNftContent required.'
            )  # noqa: E501
        content: PetMemoryNftContent = data.individual_content
        return PetMemoryNft(
            collection_id=collection_id,
            address=data.address,
            index=data.index,
            lang=content.imm_data.lang,
            name=content.imm_data.name,
            sex=content.imm_data.sex,
            species=content.imm_data.species,
            species_name=content.imm_data.species_name,
            breed=content.imm_data.breed,
            country=content.imm_data.country_code,
            geo_point_is_south=(
                content.imm_data.geo_point.is_south if content.imm_data.geo_point is not None else None
            ),
            geo_point_latitude=(
                content.imm_data.geo_point.latitude if content.imm_data.geo_point is not None else None
            ),
            geo_point_longitude=(
                content.imm_data.geo_point.longitude if content.imm_data.geo_point is not None else None
            ),
            location=content.imm_data.location,
            birth_date=content.imm_data.birth_date,
            death_date=content.imm_data.death_date,
            owner=data.owner_address,
            fee_due_time=content.fee_due_time,
            uri=content.data.uri,
            description=content.data.description,
            image=content.data.image,
            image_data=content.image_data(),
        )

    def to_nftmodel(self, collection_address: str) -> NftItemData:
        if (
            self.geo_point_is_south is not None
            and self.geo_point_latitude is not None
            and self.geo_point_longitude is not None
        ):
            geo_point = GeoPoint(
                is_south=self.geo_point_is_south, latitude=self.geo_point_latitude, longitude=self.geo_point_longitude
            )
        else:
            geo_point = None
        imm_data = PetMemoryNftImmutableData(
            species=self.species,
            name=self.name,
            sex=self.sex,
            country_code=self.country,
            birth_date=self.birth_date,
            death_date=self.death_date,
            species_name=self.species_name,
            breed=self.breed,
            lang=self.lang,
            geo_point=geo_point,
            location=self.location,
        )
        data = NftMutableMetaData(
            bag_id=self.bag_id, uri=self.uri, description=self.description, image=self.image, image_data=self.image_data
        )
        content = PetMemoryNftContent(imm_data=imm_data, data=data, fee_due_time=self.fee_due_time)
        return NftItemData(
            address=self.address,
            init=True,
            owner_address=self.owner,
            index=self.index,
            individual_content=content,
            collection_address=collection_address,
        )

    def to_nftheader(self, collection_address: str, icon_size: str = None) -> NftItemHeader:
        icons: dict[str, list[str]] = None
        if self.icons is not None:
            icons = pickle.loads(self.icons)
            icons = {
                k: [base64.encodebytes(x) for x in v]
                for k, v in icons.items()
                if not icon_size or icon_size == "all" or k == icon_size
            }
        return NftItemHeader(
            address=self.address,
            index=self.index,
            owner_address=self.owner,
            collection_address=collection_address,
            image=self.image,
            image_data=None,
            icons=icons,
        )


class NftTaskType(enum.IntEnum):
    SYNC = 1
    NOTIFY_DUE_DATE = 2
    NOTIFY_MINT = 3
    NOTIFY_UPDATED = 4


class NftTaskQueue(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    task_type: int
    task_time: datetime.datetime | None = Field(index=True)
    collection_id: int = Field(foreign_key="pets_collection.id")
    pet_memory_nft_id: int | None = Field(foreign_key="pet_memory_nft.id", default=None)
    index: int | None = Field(default=None)
    procst_time: datetime.datetime | None = Field(index=True, default=None)
    created_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    __tablename__ = "nft_task_queue"


class TgUser(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    owner: str = Field(index=True, max_length=48)
    user_id: int = Field(index=True)
    username: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=2)
    language: str | None = Field(default=None, max_length=2)
    is_premium: bool = Field(default=False)
    created_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)
    updated_time: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, nullable=False)

    __tablename__ = "tg_user"
    __table_args__ = (UniqueConstraint("owner", "user_id", name="tg_user_index_uk"),)
