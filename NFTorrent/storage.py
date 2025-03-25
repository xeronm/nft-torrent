import os
import time
import subprocess
import selectors
import json
import base64
import binascii
from dataclasses import dataclass
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

@dataclass
class TonStorageCliSettings:
    storage_cli_binary: str
    storage_cli_args: List[str]
    storage_db_path: str
    request_timeout: int = 30
    manifest_bag_id: str = None

    @classmethod
    def from_environment(cls):
        return TonStorageCliSettings(
            storage_cli_binary=os.environ.get('STORAGE_CLI_BINARY', './storage-daemon-cli'),
            storage_cli_args=os.environ.get('STORAGE_CLI_ARGS', '-I 127.0.0.1:5555'),
            storage_db_path=os.environ.get('STORAGE_DB_PATH', './storage-db'),
            request_timeout=int(os.environ.get('STORAGE_REQUEST_TIMEOUT', TonStorageCliSettings.request_timeout)),
            manifest_bag_id=os.environ.get('STORAGE_REQUEST_TIMEOUT', None),
        )

def parse_bag_id(bag_id: str | bytes) -> str:
    hex_bag_id = None
    if isinstance(bag_id, bytes):
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


class TonStorageCli:    

    def __init__(self, client_id: int, settings: TonStorageCliSettings):
        self.client_id = client_id
        self.settings = settings
        self.calls_stat: Dict[str, int] = {}
        self._proc = None

    def terminate(self):
        if self._proc is None:
            return
        
        self._proc.kill()
        self._proc.stderr.close()
        self._proc.stdout.close()
        self._proc.stdin.close()
        self._proc.wait()
        self._proc = None

    def __del__(self):
        self.terminate()

    def open(self):
        if self._proc is not None:
            return True
        
        if not os.path.isfile(self.settings.storage_cli_binary):
            raise FileExistsError(f'Binary "{self.settings.storage_cli_binary}" not exists')

        try:
            args = [ self.settings.storage_cli_binary ] + self.settings.storage_cli_args + [
                '-p', os.path.join(self.settings.storage_db_path, 'cli-keys', 'server.pub'),                    
                '-k', os.path.join(self.settings.storage_db_path, 'cli-keys', 'client'), 
            ]

            self._proc = subprocess.Popen(
                ' '.join(args),
                bufsize=65536, shell=True, 
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as E:
            logger.error('TonStorageCli #%03d: Popen error - %s', self.client_id, E)
            return False

        try:
            self._read_until('Connected', timeout=self.settings.request_timeout, stderr=True)
        except subprocess.SubprocessError as E:
            logger.error('TonStorageCli #%03d: Client communication error - %s', self.client_id, E)
            self.terminate()
            return False
        
        logger.info(f'Session opened.')        
        return True        
            
    def close(self):
        if not self.is_alive():
            return
        
        return_code = 0
        try:
            self._proc.communicate('quit\n'.encode(), timeout=self.settings.request_timeout)
        except subprocess.TimeoutExpired:
            self.terminate()
        self._proc = None        
        logger.info('TonStorageCli #%03d: Session closed, exit=%d.', self.client_id, return_code)

    def is_alive(self):
        if self._proc is None:
            return False
        
        return_code = self._proc.poll()
        if return_code is not None:
            logger.error('TonStorageCli #%03d: Session aborted, exit=%d', self.client_id, return_code)
            self.terminate()
        return return_code is None


    def _read_until(self, match: str, timeout: int = None, stderr: bool = False, match_error: str = None):
        st_time = time.monotonic()
        output = ''
        pos = 0
        with selectors.DefaultSelector() as selector:
            selector.register(self._proc.stderr if stderr else self._proc.stdout, selectors.EVENT_READ)
            while self._proc.poll() is None:
                cur_time = time.monotonic()
                if cur_time - st_time > timeout:
                    raise subprocess.TimeoutExpired(self.settings.storage_cli_binary, timeout, output=None, stderr=output)
                if selector.select(timeout=timeout - (cur_time - st_time)):
                    buffer = (self._proc.stderr if stderr else self._proc.stdout).read1().decode()
                    output += buffer
                    if match_error is not None and len(output) >= len(match_error):
                        if output.startswith(match_error):
                            return {'error': buffer.strip()}
                        match_error = None

                    if output.find(match, pos) >= 0:
                        return {'message': output.strip()}
                    pos = max(0, len(output) - len(match))        
        raise subprocess.CalledProcessError(self._proc.poll(), self.settings.storage_cli_binary, output=None, stderr=output)
                
    def _read_json(self, timeout: int = None, match_error: str = None):
        st_time = time.monotonic()
        output = ''
        
        # JSON parsing state
        quotes = False
        braces = 0
        escape = False

        with selectors.DefaultSelector() as selector:
            selector.register(self._proc.stdout, selectors.EVENT_READ)
            while self._proc.poll() is None:
                cur_time = time.monotonic()
                if cur_time - st_time > timeout:
                    raise subprocess.TimeoutExpired(self.settings.storage_cli_binary, timeout, output=output, stderr=None)
                if selector.select(timeout=timeout - (cur_time - st_time)):
                    buffer = self._proc.stdout.read1().decode()
                    output += buffer
                    if match_error is not None and len(output) >= len(match_error):
                        if output.startswith(match_error):
                            return {'error': buffer.strip()}
                        match_error = None

                    for ch in buffer:
                        if quotes:
                            if escape:
                                escape = False
                            elif ch == '\\':
                                escape = True
                            elif ch == '"':
                                quotes = False
                        else:
                            if ch == '"':
                                quotes = True
                            elif ch == '{':
                                braces += 1
                            elif ch == '}':
                                braces -= 1
                                if braces == 0:
                                    return json.loads(buffer)
                            
        raise subprocess.CalledProcessError(self._proc.poll(), self.settings.storage_cli_binary, output=output, stderr=None)

    def _run_command(self, command: str, as_json=True):
        if not self.is_alive():
            self.open()

        try:
            logger.debug('TonStorageCli #%03d: run -> %s', self.client_id, command)
            response = None
            if as_json:
                self._proc.stdin.write(f'{command} --json\n'.encode())
                self._proc.stdin.flush()
                response = self._read_json(timeout=self.settings.request_timeout, match_error='Query error:')
            else:
                self._proc.stdin.write(f'{command}\n'.encode())
                self._proc.stdin.flush()
                response = self._read_until('Success\n', timeout=self.settings.request_timeout, match_error='Query error:')

            logger.debug('TonStorageCli #%03d: response <- %s', self.client_id, json.dumps(response))
            return response
        except subprocess.SubprocessError as E:
            self.terminate()
            raise

    def node_get_state(self):
        peers = self.run_get_peers(self.settings.manifest_bag_id)
        if (isinstance(peers, dict) and 'peers' in peers):
            return [
                {'adnl_id': x['adnl_id'], 'ip_str': x['ip_str']} 
                for x in peers['peers'] 
                if x['@type'] == 'storage.daemon.peer'
            ]
        else:
            # Error
            return peers
        
    def run_list(self):
        return self._run_command('list')

    def run_add(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'add-by-hash {bag_id}') 

    def run_remove(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'remove {bag_id}', as_json=False) 

    def run_get_peers(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'get-peers {bag_id}') 

    def run_get(self, bag_id: str | bytes):        
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'get {bag_id}') 
    
    def run_create(self, path: str, description: str | dict | list = None, copy: bool = False, check_existance: bool = True):
        if not path or not isinstance(path, str):
            raise ValueError(f'Invalid path value, must be non-empty string')
        if check_existance and not os.path.isfile(path) and not os.path.isdir(path):
            raise FileExistsError(f'File or directory "{path}" not exists')        
        command = 'create '
        if description:
            str_desc = description.replace('\'', '\\\'') if isinstance(description, str) else json.dumps(description)
            command += f'-d \'{str_desc}\' '
        if copy:
            command += '--copy '
        command += path
        return self._run_command(command)


def __example():  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)

    cli = TonStorageCli(1,
        TonStorageCliSettings(
            storage_cli_binary="/mnt/c/Work/ton-storage/storage-daemon-cli.exe",
            storage_cli_args=["-I", "172.19.96.1:5555"],
            storage_db_path="C:/Work/ton-storage/storage-db",
            request_timeout=3,
            manifest_bag_id='A8C27C0AF2BB3A3077330F1857C3130F6EBEEE5BD5347A18F1A4CCD30D4F5F82'
        ))
        
    cli.open()

    peers = cli.node_get_state()
    print(peers)

    out = cli.run_list()

    out = cli.run_get('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')

    out = cli.run_add('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')    
    
    out = cli.run_get('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')
    while out['torrent']['completed'] == False:
        time.sleep(3)
        out = cli.run_get('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')

    out = cli.run_add('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')    

    out = cli.run_get_peers('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')

    out = cli.run_remove('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')

    out = cli.run_remove('F70D2F7587DBDFD0928E1967A0B2783EC3ABD63846AEC3B055B4705AEF742871')

    out = cli.run_create("C:/Work/ton-storage/file1.txt", {"nft_address": "kQDggbH8_-FjQOjYgh96uSlZpImO02o9cBberv3BQRfcw7mH"}, copy=True, check_existance=False)

    cli.run_remove(out['torrent']['hash'])

    cli.close()
