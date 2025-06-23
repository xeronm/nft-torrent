import json
import os
from abc import abstractmethod
from dataclasses import dataclass
from importlib import import_module

import requests

from NFTorrent.modelsbase import CollectionConfig


def strtobool(val):
    if val.lower() in ["y", "yes", "t", "true", "on", "1"]:
        return True
    if val.lower() in ["n", "no", "f", "false", "off", "0"]:
        return False
    raise ValueError(f"Invalid bool value {val}")


def import_string(dotted_path, importname: bool = True):
    """
    Import a dotted module path and return the attribute/class designated by the
    last name in the path. Raise ImportError if the import failed.
    """
    if not dotted_path:
        return None
    try:
        module_path, class_name = dotted_path.rsplit(".", 1)
    except ValueError as err:
        raise ImportError(f'"{dotted_path}" doesn\'t look like a module path') from err

    module = import_module(module_path)

    try:
        value = getattr(module, class_name)
        if importname:
            try:
                value.__importname__ = dotted_path
            except AttributeError:
                pass
        return value
    except AttributeError as err:
        raise ImportError(f'Module "{module_path}" does not define a "{class_name}" attribute/class') from err


def _value_from_file(value: str):
    if value and value.startswith("file:"):
        with open(value[5:]) as f:
            return f.readline().strip()
    return value


class BaseCacheManager:
    settings_class = None

    @abstractmethod
    def cached(self, expire=0, check_error=True):
        pass


@dataclass
class WebServerSettings:
    api_root_path: str
    jwt_secret: str
    jwt_algorithm: str
    port: int = None
    debug: bool = False
    remote_api_root: str = None
    public_addr: str = None
    twa_domains: list[str] = None
    bot_token: str = None
    allow_origins: list[str] = None
    enable_ssl: bool = True
    verify_ssl: bool = True
    bearer_auth_response: bool = True
    real_ip_header: bool = True
    allow_networks: list[str] = None
    request_timeout: int = 10
    collection_config: CollectionConfig = None

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.debug = strtobool(os.environ.get("HTTP_DEBUG", "false"))
        obj.api_root_path = os.environ.get("HTTP_API_ROOT_PATH", "")
        obj.remote_api_root = os.environ.get("HTTP_REMOTE_API_ROOT")
        obj.public_addr = os.environ.get("HTTP_PUBLIC_ADDR", "127.0.0.1")
        obj.jwt_secret = _value_from_file(os.environ.get("HTTP_API_JWT_SECRET", None))
        obj.jwt_algorithm = os.environ.get("HTTP_API_JWT_ALGORITHM", "HS256")
        obj.bot_token = _value_from_file(os.environ.get("HTTP_TWA_BOT_TOKEN", None))

        obj.port = os.environ.get("HTTP_PORT", None)
        if obj.port is not None:
            obj.port = int(obj.port)
        obj.enable_ssl = strtobool(os.environ.get("HTTP_ENABLE_SSL", "true"))
        obj.verify_ssl = strtobool(os.environ.get("HTTP_VERIFY_SSL", "true"))
        obj.bearer_auth_response = strtobool(os.environ.get("HTTP_BEARER_AUTH_RESPONSE", "true"))
        obj.real_ip_header = strtobool(os.environ.get("HTTP_REAL_IP_HEADER", "true"))
        obj.request_timeout = int(os.environ.get("HTTP_REQUEST_TIMEOUT", cls.request_timeout))
        obj.twa_domains = [x.strip() for x in os.environ.get("HTTP_TWA_DOMAINS", "").split(",") if x.strip()]
        obj.allow_origins = [x.strip() for x in os.environ.get("HTTP_ALLOW_ORIGINS", "").split(",") if x.strip()]
        obj.collection_config = import_string(
            os.environ.get("HTTP_COLLECTION_CONFIG", "NFTorrent.collections.config"),
        )  # noqa: E501
        obj.allow_networks = [x.strip() for x in os.environ.get("HTTP_ALLOW_NETWORKS", "").split(",") if x.strip()]
        return obj


@dataclass
class IndexDbSettings:
    enabled: bool
    database_url: str
    indexer_timeout: int = 30
    bulk_size: int = 100
    num_workers: int = 4
    max_parallel_task: int = 4
    icon_size_small: int = 100
    icon_size_medium: int = 240
    icon_format: str = "webp"
    nftorrent_apiroot: str = None
    http_timeout: int = 30

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.enabled = strtobool(os.environ.get("INDEXDB_ENABLED", "false"))
        database_backend = os.environ.get("INDEXDB_DATABASE_BACKEND", "postgresql+psycopg2")
        database_user = os.environ.get("INDEXDB_DATABASE_USER", "postgres")
        database_password = os.environ.get("INDEXDB_DATABASE_PASSWORD", "postgres")
        database_name = os.environ.get("INDEXDB_DATABASE_NAME", "postgres")
        database_host = os.environ.get("INDEXDB_DATABASE_HOST", "localhost")
        database_port = os.environ.get("INDEXDB_DATABASE_PORT", None)
        if database_port:
            database_host = f"{database_host}:{database_port}"
        obj.database_url = f"{database_backend}://{database_user}:{database_password}@{database_host}/{database_name}"
        obj.indexer_timeout = int(os.environ.get("INDEXDB_INDEXER_TIMEOUT", cls.indexer_timeout))
        obj.bulk_size = int(os.environ.get("INDEXDB_BULK_SIZE", cls.bulk_size))
        obj.num_workers = int(os.environ.get("INDEXDB_NUM_WORKERS", cls.num_workers))
        obj.max_parallel_task = int(os.environ.get("INDEXDB_MAX_PARALLEL_TASK", cls.max_parallel_task))
        obj.icon_size_small = int(os.environ.get("INDEXDB_ICON_SIZE_SMALL", cls.icon_size_small))
        obj.icon_size_medium = int(os.environ.get("INDEXDB_ICON_SIZE_MEDIUM", cls.icon_size_medium))
        obj.icon_format = os.environ.get("INDEXDB_ICON_FORMAT", cls.icon_format)
        obj.nftorrent_apiroot = os.environ.get("INDEXDB_NFTORRENT_APIROOT")
        obj.http_timeout = int(os.environ.get("INDEXDB_HTTP_TIMEOUT", cls.http_timeout))
        return obj


@dataclass
class IpfsSettings:
    enabled: bool
    kubo_rpc_uri: str
    cluster_rpc_uri: str
    request_timeout: int = 30
    confirmation_timeout: int = 60
    min_peers_count: int = 10
    min_redundancy = 3
    cid_size_limit: int = 10 * 1024 * 1024
    file_size_limit: int = 768 * 1024

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.enabled = strtobool(os.environ.get("IPFS_ENABLED", "false"))
        obj.kubo_rpc_uri = os.environ.get("IPFS_KUBO_RPC_URI", None)
        obj.cluster_rpc_uri = os.environ.get("IPFS_CLUSTER_RPC_URI", None)
        obj.request_timeout = int(os.environ.get("IPFS_RPC_TIMEOUT", cls.request_timeout))
        obj.min_peers_count = int(os.environ.get("IPFS_MIN_PEERS_COUNT", cls.min_peers_count))
        obj.min_redundancy = int(os.environ.get("IPFS_MIN_REDUNDANCY", cls.min_redundancy))
        obj.confirmation_timeout = int(os.environ.get("IPFS_CONFIRMATION_TIMEOUT", cls.confirmation_timeout))
        obj.cid_size_limit = int(os.environ.get("IPFS_STORAGE_CID_SIZE_LIMIT", cls.cid_size_limit))
        obj.file_size_limit = int(os.environ.get("IPFS_STORAGE_FILE_SIZE_LIMIT", cls.file_size_limit))
        return obj


@dataclass
class MemoryCacheSettings:
    max_size: int = 1024

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.max_size = int(os.environ.get("CACHE_MEMORY_MAX_SIZE", cls.max_size))
        return obj


@dataclass
class RedisCacheSettings:
    endpoint: str = "localhost"
    port: int = 6379
    timeout: int = 1

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.endpoint = os.environ.get("CACHE_REDIS_ENDPOINT", cls.endpoint)
        obj.port = int(os.environ.get("CACHE_REDIS_PORT", cls.port))
        obj.timeout = int(os.environ.get("CACHE_REDIS_TIMEOUT", cls.timeout))
        return obj


@dataclass
class CacheSettings:
    enabled: bool
    manager_class: BaseCacheManager
    cache_settings = None

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.enabled = strtobool(os.environ.get("CACHE_ENABLED", "false"))
        obj.manager_class = import_string(os.environ.get("CACHE_MANAGER_CLASS", "NFTorrent.cache.MemoryCacheManager"))
        if obj.manager_class.settings_class:
            obj.cache_settings = obj.manager_class.settings_class.from_environment()
        return obj


@dataclass
class TonlibSettings:
    parallel_requests: int = 50
    keystore: str = "./ton_keystore/"
    liteserver_config_path: str = "https://ton.org/global-config.json"
    request_timeout: int = 10
    verbosity_level: int = 0
    restart_timeout: int = 10
    max_liteservers: int = 16
    cdll_path: str = None

    @property
    def liteserver_config(self):
        if not hasattr(self, "_liteserver_config"):
            if self.liteserver_config_path.startswith("https://") or self.liteserver_config_path.startswith("http://"):
                self._liteserver_config = requests.get(self.liteserver_config_path).json()
            else:
                with open(self.liteserver_config_path) as f:
                    self._liteserver_config = json.load(f)
        return self._liteserver_config

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.max_liteservers = int(os.environ.get("TONLIB_MAX_LITESERVERS", cls.max_liteservers))
        obj.verbosity_level = int(os.environ.get("TONLIB_VERBOSITY_LEVEL", cls.verbosity_level))
        obj.parallel_requests = int(os.environ.get("TONLIB_PARALLEL_REQUESTS", cls.parallel_requests))
        obj.keystore = os.environ.get("TONLIB_KEYSTORE", cls.keystore)
        obj.liteserver_config_path = os.environ.get("TONLIB_LITESERVER_CONFIG", cls.liteserver_config_path)
        obj.cdll_path = os.environ.get("TONLIB_CDLL_PATH", None)
        obj.request_timeout = int(os.environ.get("TONLIB_REQUEST_TIMEOUT", cls.request_timeout))
        obj.restart_timeout = int(os.environ.get("TONLIB_RESTART_TIMEOUT", cls.restart_timeout))
        return obj


@dataclass
class Settings:
    tonlib: TonlibSettings
    webserver: WebServerSettings
    cache: CacheSettings
    indexdb: IndexDbSettings
    ipfs: IpfsSettings
    logger_level: str = "WARNING"
    logger_config: str = None

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)

        obj.logger_level = os.environ.get("LOGGER_LEVEL", cls.logger_level)
        obj.logger_config = import_string(os.environ.get("LOGGER_CONFIG", None), importname=False)  # noqa: E501
        obj.ipfs = IpfsSettings.from_environment()
        obj.webserver = WebServerSettings.from_environment()
        obj.tonlib = TonlibSettings.from_environment()
        obj.cache = CacheSettings.from_environment()
        obj.indexdb = IndexDbSettings.from_environment()
        return obj


__all__ = ["Settings"]
