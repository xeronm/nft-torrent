import os
from dataclasses import dataclass
from importlib import import_module
from typing import List

from pyTON import settings

from NFTorrent.blockchain.address import parse_bag_id
from NFTorrent.modelsbase import CollectionConfig


def import_string(dotted_path):
    """
    Import a dotted module path and return the attribute/class designated by the
    last name in the path. Raise ImportError if the import failed.
    """
    try:
        module_path, class_name = dotted_path.rsplit('.', 1)
    except ValueError as err:
        raise ImportError("%s doesn't look like a module path" % dotted_path) from err

    module = import_module(module_path)

    try:
        return getattr(module, class_name)
    except AttributeError as err:
        raise ImportError('Module "%s" does not define a "%s" attribute/class' % (
            module_path, class_name)
        ) from err


def _value_from_file(value: str):
    if value and value.startswith('file:'):
        with open(value[5:], 'r') as f:
            return f.readline().strip()
    return value


@dataclass
class TonStorageCliSettings:
    storage_public_addr: str
    storage_cli_binary: str
    storage_daemon_addr: str
    storage_db_path: str
    storage_temp_dir: str = None
    storage_db_torrent_path: str = None
    storage_size_pressure = 1000
    storage_max_size = None
    storage_bag_size_limit = 8*1024*1024
    request_timeout: int = 5
    manifest_bag_id: str = None
    num_workers: int = 16
    restart_timeout: int = 30
    confirmation_timeout = 60
    min_redundancy = 3
    torrent_dirname: str = 'nftdata'

    @property
    def enabled(self) -> bool:
        return self.num_workers > 0

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.storage_public_addr = os.environ.get('TON_STORAGE_PUBLIC_ADDR', None)
        obj.storage_cli_binary = os.environ.get('TON_STORAGE_CLI_BINARY', './storage-daemon-cli')
        obj.storage_daemon_addr = os.environ.get('TON_STORAGE_DAEMON_ADDR', '127.0.0.1:5555')
        obj.storage_db_path = os.environ.get('TON_STORAGE_DB_PATH', './storage-db')
        obj.storage_temp_dir = os.environ.get('TON_STORAGE_TEMP_DIR', None)
        obj.storage_db_torrent_path = os.environ.get('TON_STORAGE_DB_TORRENT_PATH', None)
        obj.storage_size_pressure = int(os.environ.get('TON_STORAGE_SIZE_PRESSURE', cls.storage_size_pressure))
        obj.storage_max_size = int(os.environ.get('TON_STORAGE_MAX_SIZE', round(obj.storage_size_pressure * 1.5)))
        obj.storage_bag_size_limit = int(os.environ.get('TON_STORAGE_BAG_SIZE_LIMIT', cls.storage_bag_size_limit))
        obj.request_timeout = int(os.environ.get('TON_STORAGE_REQUEST_TIMEOUT', cls.request_timeout))
        obj.num_workers = int(os.environ.get('TON_STORAGE_NUM_WORKERS', cls.num_workers))
        obj.restart_timeout = int(os.environ.get('TON_STORAGE_WORKERS_RESTART_TIMEOUT', cls.restart_timeout))
        obj.confirmation_timeout = int(os.environ.get('TON_STORAGE_CONFIRMATION_TIMEOUT', cls.confirmation_timeout))
        obj.min_redundancy = int(os.environ.get('TON_STORAGE_MIN_REDUNDANCY', cls.min_redundancy))
        obj.torrent_dirname = os.environ.get('TON_STORAGE_TORRENT_DIRNAME', cls.torrent_dirname)
        try:
            obj.manifest_bag_id = parse_bag_id(_value_from_file(os.environ.get('TON_STORAGE_MANIFEST_BAG_ID', None)))
        except:
            obj.manifest_bag_id = None
        if not obj.storage_public_addr and obj.num_workers:
            raise ValueError('Environemnt variable "TON_STORAGE_PUBLIC_ADDR" is required')
        return obj


@dataclass
class WebServerSettings:
    api_root_path: str
    jwt_secret: str
    jwt_algorithm: str
    port: int = None
    debug: bool = False
    remote_api_root: str = None
    twa_domains: List[str] = None
    allow_origins: List[str] = None
    enable_ssl: bool = True
    verify_ssl: bool = True
    bearer_auth_response: bool = True
    real_ip_header: bool = True
    allow_networks: List[str] = None
    request_timeout: int = 10
    collection_config: CollectionConfig = None

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.debug = settings.strtobool(os.environ.get('HTTP_DEBUG', 'false'))
        obj.api_root_path = os.environ.get('HTTP_API_ROOT_PATH', '/')
        obj.remote_api_root = os.environ.get('HTTP_REMOTE_API_ROOT')
        obj.jwt_secret = _value_from_file(os.environ.get('HTTP_API_JWT_SECRET', None))
        obj.jwt_algorithm = os.environ.get('HTTP_API_JWT_ALGORITHM', 'HS256')
        obj.port = os.environ.get('HTTP_PORT', None)
        if obj.port is not None:
            obj.port = int(obj.port)
        obj.enable_ssl = settings.strtobool(os.environ.get('HTTP_ENABLE_SSL', 'true'))
        obj.verify_ssl = settings.strtobool(os.environ.get('HTTP_VERIFY_SSL', 'true'))
        obj.bearer_auth_response = settings.strtobool(os.environ.get('HTTP_BEARER_AUTH_RESPONSE', 'true'))
        obj.real_ip_header = settings.strtobool(os.environ.get('HTTP_REAL_IP_HEADER', 'true'))
        obj.request_timeout = int(os.environ.get('HTTP_REQUEST_TIMEOUT', cls.request_timeout))
        obj.twa_domains = [x.strip() for x in os.environ.get('HTTP_TWA_DOMAINS', '').split(',') if x.strip()]
        obj.allow_origins = [x.strip() for x in os.environ.get('HTTP_ALLOW_ORIGINS', '').split(',') if x.strip()]
        obj.collection_config = import_string(os.environ.get('HTTP_COLLECTION_CONFIG', 'NFTorrent.collections.config'))  # noqa: E501
        obj.allow_networks = [x.strip() for x in os.environ.get('HTTP_ALLOW_NETWORKS', '').split(',') if x.strip()]
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
    icon_format: str = 'webp'
    nftorrent_apiroot: str = None
    http_timeout: int = 30

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.enabled = settings.strtobool(os.environ.get('INDEXDB_ENABLED', 'false'))
        database_backend = os.environ.get('INDEXDB_DATABASE_BACKEND', 'postgresql+psycopg2')
        database_user = os.environ.get('INDEXDB_DATABASE_USER', 'postgres')
        database_password = os.environ.get('INDEXDB_DATABASE_PASSWORD', 'postgres')
        database_name = os.environ.get('INDEXDB_DATABASE_NAME', 'postgres')
        database_host = os.environ.get('INDEXDB_DATABASE_HOST', 'localhost')
        database_port = os.environ.get('INDEXDB_DATABASE_PORT', None)
        if database_port:
            database_host = f'{database_host}:{database_port}'
        obj.database_url = f'{database_backend}://{database_user}:{database_password}@{database_host}/{database_name}'
        obj.indexer_timeout = int(os.environ.get('INDEXDB_INDEXER_TIMEOUT', cls.indexer_timeout))
        obj.bulk_size = int(os.environ.get('INDEXDB_BULK_SIZE', cls.bulk_size))
        obj.num_workers = int(os.environ.get('INDEXDB_NUM_WORKERS', cls.num_workers))
        obj.max_parallel_task = int(os.environ.get('INDEXDB_MAX_PARALLEL_TASK', cls.max_parallel_task))
        obj.icon_size_small = int(os.environ.get('INDEXDB_ICON_SIZE_SMALL', cls.icon_size_small))
        obj.icon_size_medium = int(os.environ.get('INDEXDB_ICON_SIZE_MEDIUM', cls.icon_size_medium))
        obj.icon_format = os.environ.get('INDEXDB_ICON_FORMAT', cls.icon_format)
        obj.nftorrent_apiroot = os.environ.get('INDEXDB_NFTORRENT_APIROOT')
        obj.http_timeout = int(os.environ.get('INDEXDB_HTTP_TIMEOUT', cls.http_timeout))
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
    cid_size_limit: int = 10*1024*1024
    file_size_limit: int = 768*1024

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.enabled = settings.strtobool(os.environ.get('IPFS_ENABLED', 'false'))
        obj.kubo_rpc_uri = os.environ.get('IPFS_KUBO_RPC_URI', None)
        obj.cluster_rpc_uri = os.environ.get('IPFS_CLUSTER_RPC_URI', None)
        obj.request_timeout = int(os.environ.get('IPFS_RPC_TIMEOUT', cls.request_timeout))
        obj.min_peers_count = int(os.environ.get('IPFS_MIN_PEERS_COUNT', cls.min_peers_count))
        obj.min_redundancy = int(os.environ.get('IPFS_MIN_REDUNDANCY', cls.min_redundancy))
        obj.confirmation_timeout = int(os.environ.get('IPFS_CONFIRMATION_TIMEOUT', cls.confirmation_timeout))
        obj.cid_size_limit = int(os.environ.get('IPFS_STORAGE_CID_SIZE_LIMIT', cls.cid_size_limit))
        obj.file_size_limit = int(os.environ.get('IPFS_STORAGE_FILE_SIZE_LIMIT', cls.file_size_limit))
        return obj


@dataclass
class Settings:
    tonlib: settings.TonlibSettings
    webserver: WebServerSettings
    cache: settings.CacheSettings
    storage: TonStorageCliSettings
    indexdb: IndexDbSettings
    ipfs: IpfsSettings

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.storage = TonStorageCliSettings.from_environment()
        obj.ipfs = IpfsSettings.from_environment()
        obj.webserver = WebServerSettings.from_environment()
        _pyton = settings.Settings.from_environment()
        obj.tonlib = _pyton.tonlib
        obj.cache = _pyton.cache
        obj.indexdb = IndexDbSettings.from_environment()
        return obj
