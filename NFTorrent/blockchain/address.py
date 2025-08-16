import base64
import binascii

from pytonlib.utils.address import account_forms, calcCRC, is_hex, is_int, read_friendly_address


def adnl_id_encode(adnl_id: bytes, upper_case: bool = False) -> str:
    if len(adnl_id) != 32:
        raise ValueError("Invalid ADNL id length, 32 bytes expected")
    buffer = b"\x2d" + adnl_id
    adnl_enc = base64.b32encode(buffer + calcCRC(buffer))[1:].decode()
    return adnl_enc if upper_case else adnl_enc.lower()


def adnl_id_decode(id: str) -> bytes:
    if len(id) != 55:
        raise ValueError("Invalid ADNL id length, 55 chars expected")
    buffer = chr(0x66) + id
    adnl_dec = base64.b32decode(buffer.upper())
    if adnl_dec[0] != 0x2D:
        raise ValueError("ADNL decoding error: invalid first byte")
    if calcCRC(adnl_dec[:33]) != adnl_dec[33:]:
        raise ValueError("ADNL decoding error: invalid checksum")
    return adnl_dec[1:33]


def parse_adnl_id(adnl_id: bytes | str) -> str:
    buf = None
    if isinstance(adnl_id, str):
        if len(adnl_id) == 55:
            adnl_id_decode(adnl_id)
            return adnl_id

        valid = True
        if len(adnl_id) == 64:
            try:
                buf = bytes.fromhex(adnl_id)
            except ValueError:
                valid = False
        else:
            try:
                buf = base64.b64decode(adnl_id, validate=True)
            except binascii.Error:
                valid = False
        if not valid or len(buf) != 32:
            raise ValueError("Invalid adnl id str: should be 32 bytes hex or base64 encoded")
    else:
        buf = adnl_id
    return adnl_id_encode(buf)


def parse_bag_id(bag_id: int | str | bytes) -> str:
    hex_bag_id = None
    if isinstance(bag_id, int):
        hex_bag_id = hex(bag_id)[2:].rjust(64, "0")
    elif isinstance(bag_id, bytes):
        if len(bag_id) != 32:
            raise ValueError("Invalid bag id: should be 16 bytes")
        hex_bag_id = bag_id.hex()
    else:
        valid = True
        if len(bag_id) == 64:  # HEX representation
            try:
                buf = bytes.fromhex(bag_id)
            except ValueError:
                valid = False
            hex_bag_id = bag_id
        else:  # base64 representation
            try:
                buf = base64.b64decode(bag_id, validate=True)
                hex_bag_id = buf.hex()
            except binascii.Error:
                buf = None
        if buf is None or len(buf) != 32:
            valid = False
        if not valid:
            raise ValueError("Invalid bag id: should be 32 bytes hex or base64 encoded")
    return hex_bag_id.upper()


def parse_address(address: bytes | str):
    if isinstance(address, bytes):
        address = address.hex()
    if len(address) == 64 and is_hex(address):
        return account_forms("-1:" + address)
    elif ":" in address:
        workchain, _address = address.split(":")
        if is_hex(_address) and len(_address) == 64 and is_int(workchain):
            return account_forms(address)
        else:
            raise ValueError("Invalid raw address format")
    else:
        return read_friendly_address(address)
