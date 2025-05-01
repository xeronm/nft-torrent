from bitstring import BitArray
from tonpy.types import CellSlice

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
                _chars[j] = "-"
                if (n >> (i - 8)) & 0xFF == 0:
                    j += 1
                    _chars[j] = "*"
                    i = 0
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
