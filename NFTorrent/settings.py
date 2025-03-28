import os
from dataclasses import dataclass, fields

from pyTON import settings

@dataclass
class TonStorageCliSettings:
    storage_cli_binary: str
    storage_daemon_addr: str
    storage_db_path: str
    storage_db_torrent_path: str = None
    request_timeout: int = 5
    manifest_bag_id: str = None
    num_workers: int = 16
    restart_timeout: int = 30
    confirmation_timeout = 60 
    min_redundancy = 3
    gateway_port = 8080
    torrent_dirname: str = 'nftdata'

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)        
        obj.storage_cli_binary = os.environ.get('STORAGE_CLI_BINARY', './storage-daemon-cli')
        obj.storage_daemon_addr = os.environ.get('STORAGE_DAEMON_ADDR', '127.0.0.1:5555')
        obj.storage_db_path = os.environ.get('STORAGE_DB_PATH', './storage-db')
        obj.storage_db_torrent_path = os.environ.get('STORAGE_DB_TORRENT_PATH', None)
        obj.request_timeout = int(os.environ.get('STORAGE_REQUEST_TIMEOUT', cls.request_timeout))
        obj.manifest_bag_id = os.environ.get('STORAGE_MANIFEST_BAG_ID', None)
        obj.num_workers = int(os.environ.get('STORAGE_NUM_WORKERS', cls.num_workers))
        obj.restart_timeout = int(os.environ.get('STORAGE_WORKERS_RESTART_TIMEOUT', cls.restart_timeout))
        obj.confirmation_timeout = int(os.environ.get('STORAGE_CONFIRMATION_TIMEOUT', cls.confirmation_timeout))
        obj.min_redundancy = int(os.environ.get('STORAGE_MIN_REDUNDANCY', cls.min_redundancy))
        obj.gateway_port = int(os.environ.get('STORAGE_GATEWAY_PORT', cls.gateway_port))
        obj.torrent_dirname = os.environ.get('STORAGE_TORRENT_DIRNAME', cls.torrent_dirname)
        return obj


@dataclass
class Settings:
    tonlib: settings.TonlibSettings
    webserver: settings.WebServerSettings
    cache: settings.CacheSettings
    storage: TonStorageCliSettings

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)        
        obj.storage = TonStorageCliSettings.from_environment()
        _pyton = settings.Settings.from_environment()
        for field in fields(_pyton):
            setattr(obj, field.name, getattr(_pyton, field.name))
        return obj
