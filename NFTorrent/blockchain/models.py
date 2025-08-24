import codecs
from dataclasses import dataclass

from tonpy.types import CellSlice

from ..modelsbase import BaseNftContent
from .encoders import bcd2c_to_string, date_mask_to_string, flatten_snake_cell

SPECIES = [
    "Other",
    "Dog",
    "Cat",
    "Hamster/Guinea Pig",
    "Rabbit",
    "Parrot",
    "Fish",
    "Turtle",
    "Reptile",
    "Horse/Pony",
    "Hedgehog",
    "Mouse/Rat",
    "Ferret",
    "Reserved",
    "Reserved",
    "Reserved",
]


@dataclass
class GeoPoint:
    is_south: bool
    latitude: float
    longitude: float

    @classmethod
    def from_tvm(cls, v: int):
        obj = cls.__new__(cls)
        obj.is_south = (v >> 47) & 1 == 1
        obj.latitude = ((v >> 24) & 0x7FFFFF) * 90 / (1 << 23)
        obj.longitude = (v & 0xFFFFFF) * 360 / (1 << 24)
        return obj


@dataclass
class PetMemoryNftImmutableData:
    species: int
    name: str
    sex: int
    birth_date: str
    death_date: str
    country_code: str | None = None
    species_name: str | None = None
    breed: str | None = None
    lang: str | None = None
    geo_point: GeoPoint | None = None
    location: str | None = None

    @classmethod
    def from_tvm(cls, cs: CellSlice):
        obj = cls.__new__(cls)
        _sc0 = cs
        obj.species = _sc0.load_uint(4)
        obj.name = _sc0.load_ref(as_cs=True).load_string()
        obj.sex = _sc0.load_uint(1)
        obj.species_name = _sc0.load_ref(as_cs=True).load_string() if _sc0.load_uint(1) else None

        _sc1 = _sc0.load_ref(as_cs=True)
        obj.breed = _sc1.load_ref(as_cs=True).load_string() if _sc1.load_uint(1) else None
        obj.lang = bcd2c_to_string(_sc1.load_uint(10)) if _sc1.load_uint(1) else None
        obj.country_code = bcd2c_to_string(_sc1.load_uint(10))
        obj.geo_point = GeoPoint.from_tvm(_sc1.load_uint(48)) if _sc1.load_uint(1) else None
        obj.location = _sc1.load_ref(as_cs=True).load_string() if _sc1.load_uint(1) else None
        obj.birth_date = date_mask_to_string(_sc1.load_uint(32))
        obj.death_date = date_mask_to_string(_sc1.load_uint(32))
        return obj


@dataclass
class NftMutableMetaData:
    uri: str = None
    description: str = None
    image: str = None
    image_data: str = None

    @classmethod
    def from_tvm(cls, cs: CellSlice):
        obj = cls.__new__(cls)
        _sc0 = cs
        obj.uri = _sc0.load_ref(as_cs=True).load_string() if _sc0.load_uint(1) else None
        obj.description = _sc0.load_ref(as_cs=True).load_string() if _sc0.load_uint(1) else None
        _sc1 = _sc0.load_ref(as_cs=True)
        obj.image = _sc1.load_ref(as_cs=True).load_string() if _sc1.load_uint(1) else None

        obj.image_data = None
        if _sc1.load_uint(1):
            _img = _sc1.load_ref(as_cs=True)
            if _img.load_uint(8) != 0:  # CONTENT_DATA_FORMAT_SNAKE
                raise ValueError("Only snake format is supported")
            obj.image_data = codecs.encode(flatten_snake_cell(_img), "base64")
        return obj


@dataclass
class PetMemoryNftContent(BaseNftContent):
    imm_data: PetMemoryNftImmutableData
    data: NftMutableMetaData
    fee_due_time: int = None

    @classmethod
    def from_tvm(cls, cs: CellSlice):
        _sc0 = cs
        _sc1 = _sc0.load_ref(as_cs=True)
        imm_data = PetMemoryNftImmutableData.from_tvm(_sc1)
        _sc2 = _sc1.load_ref(as_cs=True)
        data = NftMutableMetaData.from_tvm(_sc2)
        fee_due_time = _sc2.load_uint(32)
        return PetMemoryNftContent(imm_data=imm_data, data=data, fee_due_time=fee_due_time)

    def uri(self):
        return self.data.uri

    def image(self):
        return self.data.image

    def image_data(self):
        if not self.data.image_data:
            return None
        return codecs.decode(self.data.image_data, "base64")

    def storage_due_time(self):
        return self.fee_due_time

    def title(self):
        return self.imm_data.name

    def subtitle(self):
        return self.imm_data.breed if self.imm_data.breed else self.species()

    def species(self):
        return self.imm_data.species_name if self.imm_data.species_name else SPECIES[self.imm_data.species]

    def metadata_attributes(self, webapp: str = None, miniapp: str = None):
        gp = self.imm_data.geo_point
        attrs = {
            "name": self.imm_data.name,
            "species": self.species(),
            "breed": self.imm_data.breed,
            "sex": "Female" if self.imm_data.sex else "Male",
            "birth_date": self.imm_data.birth_date,
            "death_date": self.imm_data.death_date,
            "country_code": self.imm_data.country_code,
            "language": self.imm_data.lang,
            "location": self.imm_data.location,
            "geo_point": (
                f"{(-1 if gp.is_south else 1)*gp.latitude:.06f}:{gp.longitude:.06f}"
                if self.imm_data.geo_point is not None
                else None
            ),
            "fee_due_time": self.fee_due_time,
        }
        if self.data.image is not None:
            attrs["image"] = self.data.image
        if self.data.uri is not None:
            attrs["uri"] = self.data.uri
        if webapp:
            attrs["webapp"] = webapp
        if miniapp:
            attrs["miniapp"] = miniapp
        return [{"trait_type": k, "value": v} for k, v in attrs.items()]


def load_string(stack, opt: bool = False):
    if opt and "bytes" not in stack[1]:
        return None
    return CellSlice(stack[1]["bytes"]).load_string()


def load_address(stack, opt: bool = False):
    if opt and "bytes" not in stack[1]:
        return None
    return CellSlice(stack[1]["bytes"]).load_address().serialize()


@dataclass
class PetsCollectionInfo:
    fee_storage: float
    fee_class_a: float
    fee_class_b: float
    balance: float
    balance_class_a: float
    balance_class_b: float
    fb_mode: int
    fb_uri: str
    minter: str | None = None

    @classmethod
    def from_tvm(cls, stack: list):
        if len(stack) not in [8, 9]:
            raise ValueError(f"Invalid PetsCollectionInfo response length: {len(stack)}")

        minter = None
        if len(stack) > 8:
            minter = load_address(stack[0])
            stack = stack[1:]

        return PetsCollectionInfo(
            fee_storage=int(stack[0][1], 16) / 1e9,
            fee_class_a=int(stack[1][1], 16) / 1e9,
            fee_class_b=int(stack[2][1], 16) / 1e9,
            balance=int(stack[3][1], 16) / 1e9,
            balance_class_a=int(stack[4][1], 16) / 1e9,
            balance_class_b=int(stack[5][1], 16) / 1e9,
            fb_mode=int(stack[6][1], 16),
            fb_uri=load_string(stack[7]),
            minter=minter,
        )
