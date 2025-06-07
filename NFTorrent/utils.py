from dataclasses import fields
from mimetypes import guess_type as _guess_type
from mimetypes import types_map
from urllib.parse import urlparse

# fixes types_map for earlier versions
if ".webp" not in types_map:
    types_map[".webp"] = "image/webp"


def guess_type(url: str, strict: bool = True, default_type: str = None, default_encoding: str = None):
    mime_type, encodings = _guess_type(url, strict=strict)
    return mime_type or default_type, encodings or default_encoding


def dataclass_to_influx(instance):
    kv = []
    for _field in fields(instance):
        value = getattr(instance, _field.name, None)
        if value is None:
            continue
        if issubclass(_field.type, str):
            if not isinstance(value, str):
                value = str(value)
            value = '"' + value.replace('"', '\\"') + '"'
        kv.append(f"{_field.name}={value}")
    return ",".join(kv)


def dict_to_influx(instance: dict):
    kv = []
    for k, v in instance.items():
        value = v
        if value is None:
            continue
        if isinstance(v, dict):
            continue
        elif isinstance(v, bool):
            value = int(value)
        elif isinstance(v, str):
            value = '"' + value.replace('"', '\\"') + '"'
        kv.append(f"{k}={value}")
    return ",".join(kv)


SCHEME_IPFS = "ipfs"


def parse_ipfs_uri(uri: str) -> tuple[str, str, str]:
    comp = urlparse(uri)
    cid = path = digest = None
    if comp[0] == SCHEME_IPFS:
        cid, path, digest = comp[1], comp[2], comp[5]
        if path and path[0] == "/":
            path = path[1:]
    return cid, path, digest


__all__ = ["guess_type", "dataclass_to_influx", "dict_to_influx"]
