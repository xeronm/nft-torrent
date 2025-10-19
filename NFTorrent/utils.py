import re
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


def influx_escape_value(value: str) -> str:
    return re.sub(r"([ ,=])", r"\\\1", value)


def dataclass_to_influx(instance, excludes: list[str] = None):
    kv = []
    for _field in fields(instance):
        if excludes and _field.name in set(excludes):
            continue
        value = getattr(instance, _field.name, None)
        if value is None:
            continue
        if not isinstance(value, str | int | float | bool):
            continue
        if isinstance(value, bool):
            value = 1 if value else 0
        if issubclass(_field.type, str):
            if not isinstance(value, str):
                value = str(value)
            value = influx_escape_value(value) or "null"
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
            value = influx_escape_value(value) or "null"
        kv.append(f"{k}={value}")
    return ",".join(kv)


SCHEME_IPFS = "ipfs"
SUPPORTED_SCHEMES = {"http", "https", "ipfs"}


def uri_ipfs(uri: str) -> bool:
    return uri and uri.startswith(f"{SCHEME_IPFS}://")


def uri_supported(uri: str) -> bool:
    comp = urlparse(uri)
    return comp.scheme and comp.netloc and comp.scheme.lower() in SUPPORTED_SCHEMES


def parse_ipfs_uri(uri: str) -> tuple[str, str, str]:
    comp = urlparse(uri)
    cid = path = digest = None
    if comp[0] == SCHEME_IPFS:
        cid, path, digest = comp[1], comp[2], comp[5]
        if path and path[0] == "/":
            path = path[1:]
    return cid, path, digest


__all__ = ["guess_type", "dataclass_to_influx", "dict_to_influx", "uri_supported", "parse_ipfs_uri", "uri_ipfs"]
