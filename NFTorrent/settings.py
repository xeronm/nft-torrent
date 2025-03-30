import os
import base64
import binascii
from dataclasses import dataclass, fields

from pyTON import settings

def parse_bag_id(bag_id: int | str | bytes) -> str:
    hex_bag_id = None
    if isinstance(bag_id, int):
        hex_bag_id = hex(bag_id)[2:].rjust(64, '0')
    elif isinstance(bag_id, bytes):
        if len(bag_id) != 32:
            raise ValueError('Invalid bag id: should be 16 bytes')
        hex_bag_id = bag_id.hex()
    else:
        valid = True
        if len(bag_id) == 64: # HEX representation
            try:
                buf = bytes.fromhex(bag_id)            
            except ValueError:
                valid = False
            hex_bag_id = bag_id
        else: # base64 representation
            try:
                buf = base64.b64decode(bag_id, validate=True)
                hex_bag_id = buf.hex()
            except binascii.Error:
                buf = None            
        if buf is None or len(buf) != 32:
            valid = False
        if not valid:
            raise ValueError('Invalid bag id: should be 32 bytes hex')
    return hex_bag_id.upper()

@dataclass
class TonStorageCliSettings:
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
    gateway_port = 80
    torrent_dirname: str = 'nftdata'

    @classmethod
    def from_environment(cls):
        obj = cls.__new__(cls)        
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
        obj.gateway_port = int(os.environ.get('TON_STORAGE_GATEWAY_PORT', cls.gateway_port))
        obj.torrent_dirname = os.environ.get('TON_STORAGE_TORRENT_DIRNAME', cls.torrent_dirname)

        obj.manifest_bag_id = os.environ.get('TON_STORAGE_MANIFEST_BAG_ID', None)        
        if obj.manifest_bag_id and obj.manifest_bag_id.startswith('file:'):
            with open(obj.manifest_bag_id[5:], 'r') as f:
                obj.manifest_bag_id = f.readline()

        obj.manifest_bag_id = parse_bag_id(obj.manifest_bag_id)

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
