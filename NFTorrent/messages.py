import codecs
from tonpy.types import CellSlice
from bitstring import BitArray

from NFTorrent.address import parse_bag_id

# BCD encoded date mask
# 4 octets - year; 2 Octets - month; 2 octets - day; 0x00 - means unspecified or unknown
#    0x20250100 - means 2025-01-*
#    0x20250000 - means 2025-*
def date_mask_to_string(n: int) -> str:
    _chars = ['']*10
    j = 0
    if (n >> 16) & 0xFFFF:
        i = 28
        while i >= 0:
            _chars[j] = chr(((n >> i) & 0xF) + 48)
            if (i == 16) or (i == 8):
                j += 1
                if (n >> (i - 8)) & 0xFF:
                    _chars[j] = "-"
                else:
                    i = 0
                    _chars[j] = "*"                    
            j += 1
            i -= 4
        return ''.join(_chars)
    else:
        return "*"

# BCD 5-bits encoded 2-letter english char code
#   used for ISO 639 two letter language code or ISO 3166-1 alpha-2 code
def bcd2c_to_string(n: int) -> str:
    return chr(((n >> 5) & 0x1F) + 65) + chr((n & 0x1F) + 65)


def flatten_snake_cell(cs: CellSlice) -> bytes:
    buffer = []
    while cs:
        buffer.append(BitArray(bin=cs.to_bitstring()).tobytes())
        cs = cs.load_ref(as_cs=True) if cs.refs else None
    return b''.join(buffer)

class TvmStructure:
    pass

class PetMemoryNftImmutableData(TvmStructure):

    def __init__(self, cs: CellSlice):
        _sc0 = cs
        self.species = _sc0.load_uint(4)
        self.name = _sc0.load_ref(as_cs=True).load_string()
        self.sex = _sc0.load_uint(1) 
        self.species_name = _sc0.load_ref(as_cs=True).load_string() if _sc0.load_uint(1) else None

        _sc1 = _sc0.load_ref(as_cs=True)
        self.breed = _sc1.load_ref(as_cs=True).load_string() if _sc1.load_uint(1) else None
        self.lang = bcd2c_to_string(_sc1.load_uint(10)) if _sc1.load_uint(1) else None
        self.country_code = bcd2c_to_string(_sc1.load_uint(10))
        self.location = _sc1.load_ref(as_cs=True).load_string() if _sc1.load_uint(1) else None
        self.birth_date = date_mask_to_string(_sc1.load_uint(32))
        self.death_date = date_mask_to_string(_sc1.load_uint(32))


class NftMutableMetaData(TvmStructure):

    def __init__(self, cs: CellSlice):
        _sc0 = cs
        self.bag_id = parse_bag_id(_sc0.load_uint(256)) if _sc0.load_uint(1) else None
        self.uri = _sc0.load_ref(as_cs=True).load_string() if _sc0.load_uint(1) else None
        self.description = _sc0.load_ref(as_cs=True).load_string() if _sc0.load_uint(1) else None
        _sc1 = _sc0.load_ref(as_cs=True)
        self.image = _sc1.load_ref(as_cs=True).load_string() if _sc1.load_uint(1) else None

        self.imageData = None
        if _sc1.load_uint(1):            
            _img = _sc1.load_ref(as_cs=True)
            if _img.load_uint(8) != 0: # CONTENT_DATA_FORMAT_SNAKE
                raise ValueError('Only snake format is supported')            
            self.imageData = codecs.encode(flatten_snake_cell(_img), 'base64')

class PetMemoryNftContent(TvmStructure):

    def __init__(self, cs: CellSlice):
        _sc0 = cs
        _sc1 = _sc0.load_ref(as_cs=True)
        self.imm_data = PetMemoryNftImmutableData(_sc1)
        _sc2 = _sc1.load_ref(as_cs=True)
        self.data = NftMutableMetaData(_sc2)
        self.fee_due_time = _sc2.load_uint(32) 

    def bag_id(self):
        return self.data.bag_id