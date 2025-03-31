import os
import base64
import binascii
from dataclasses import dataclass, fields

from pyTON import settings

from NFTorrent.address import parse_bag_id

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
    storage_db_torrent_path: str = None
    storage_size_pressure = 10000
    request_timeout: int = 5
    manifest_bag_id: str = None
    num_workers: int = 16
    restart_timeout: int = 30
    confirmation_timeout = 60 
    min_redundancy = 3
    torrent_dirname: str = 'nftdata'

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.storage_public_addr = os.environ.get('TON_STORAGE_PUBLIC_ADDR', None)        
        obj.storage_cli_binary = os.environ.get('TON_STORAGE_CLI_BINARY', './storage-daemon-cli')
        obj.storage_daemon_addr = os.environ.get('TON_STORAGE_DAEMON_ADDR', '127.0.0.1:5555')
        obj.storage_db_path = os.environ.get('TON_STORAGE_DB_PATH', './storage-db')
        obj.storage_db_torrent_path = os.environ.get('TON_STORAGE_DB_TORRENT_PATH', None)
        obj.storage_size_pressure = int(os.environ.get('TON_STORAGE_SIZE_PRESSURE', cls.storage_size_pressure))
        obj.request_timeout = int(os.environ.get('TON_STORAGE_REQUEST_TIMEOUT', cls.request_timeout))
        obj.num_workers = int(os.environ.get('TON_STORAGE_NUM_WORKERS', cls.num_workers))
        obj.restart_timeout = int(os.environ.get('TON_STORAGE_WORKERS_RESTART_TIMEOUT', cls.restart_timeout))
        obj.confirmation_timeout = int(os.environ.get('TON_STORAGE_CONFIRMATION_TIMEOUT', cls.confirmation_timeout))
        obj.min_redundancy = int(os.environ.get('TON_STORAGE_MIN_REDUNDANCY', cls.min_redundancy))
        obj.torrent_dirname = os.environ.get('TON_STORAGE_TORRENT_DIRNAME', cls.torrent_dirname)
        obj.manifest_bag_id = parse_bag_id(_value_from_file(os.environ.get('TON_STORAGE_MANIFEST_BAG_ID', None)))

        if not obj.storage_public_addr:
            raise ValueError('Environemnt variable "TON_STORAGE_PUBLIC_ADDR" is required')

        return obj


@dataclass
class WebServerSettings:
    api_root_path: str
    jwt_secret: str
    jwt_algorithm: str
    port: int = None
    enable_ssl: bool = True
    verify_ssl: bool = True
    real_ip_header: bool = True
    request_timeout: int = 10

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)
        obj.api_root_path = os.environ.get('HTTP_API_ROOT_PATH', '/')
        obj.jwt_secret = _value_from_file(os.environ.get('HTTP_JWT_SECRET', None))
        obj.jwt_algorithm = os.environ.get('HTTP_JWT_ALGORITHM', 'HS256')
        obj.port = os.environ.get('HTTP_PORT', None)
        if obj.port is not None:
            obj.port = int(obj.port)
        obj.enable_ssl = settings.strtobool(os.environ.get('HTTP_ENABLE_SSL', 'true'))
        obj.verify_ssl = settings.strtobool(os.environ.get('HTTP_VERIFY_SSL', 'true'))
        obj.real_ip_header = settings.strtobool(os.environ.get('HTTP_REAL_IP_HEADER', 'true'))
        obj.request_timeout = int(os.environ.get('HTTP_REQUEST_TIMEOUT', cls.request_timeout))

        return obj


@dataclass
class Settings:
    tonlib: settings.TonlibSettings
    webserver: WebServerSettings
    cache: settings.CacheSettings
    storage: TonStorageCliSettings

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)        
        obj.storage = TonStorageCliSettings.from_environment()
        obj.webserver = WebServerSettings.from_environment()
        _pyton = settings.Settings.from_environment()
        obj.tonlib = _pyton.tonlib
        obj.cache = _pyton.cache

        return obj
