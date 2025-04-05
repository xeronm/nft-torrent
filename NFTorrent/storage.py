import os
import time
import subprocess
import selectors
import json
from typing import Dict, Any
from threading import RLock

from NFTorrent.settings import TonStorageCliSettings
from NFTorrent.address import parse_bag_id, parse_adnl_id

from loguru import logger


class TonStorageCli:    

    def __init__(self, client_id: int, settings: TonStorageCliSettings):
        self.client_id = client_id
        self.settings = settings
        self.calls_stat: Dict[str, int] = {}
        self._proc = None
        self.last_error = None

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
            args = [ 
                self.settings.storage_cli_binary, 
                '-I', self.settings.storage_daemon_addr,
                '-p', os.path.join(self.settings.storage_db_path, 'cli-keys', 'server.pub'),                    
                '-k', os.path.join(self.settings.storage_db_path, 'cli-keys', 'client'), 
            ]
            command = ' '.join(args) 
            logger.debug("TonStorageCli #{client_id:03d}: Popen cmd: {cmd}", client_id=self.client_id, cmd=command)

            self._proc = subprocess.Popen(
                command,
                bufsize=65536, shell=True, 
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as E:
            logger.error("TonStorageCli #{client_id:03d}: Popen error - {exc}", client_id=self.client_id, exc=E)
            return False

        try:
            self._read_until('Connected', timeout=self.settings.request_timeout, stderr=True)
        except subprocess.SubprocessError as E:
            logger.error("TonStorageCli #{client_id:03d}: Client communication error - {exc}", client_id=self.client_id, exc=E)
            self.terminate()
            return False
        
        logger.info("Session opened.")
        return True        
            
    def close(self):
        if not self.is_alive():
            return
        
        returncode = 0
        try:
            self._proc.communicate('quit\n'.encode(), timeout=self.settings.request_timeout)            
            returncode = self._proc.returncode
        except subprocess.TimeoutExpired:
            returncode = -1
            self.terminate()
        logger.info("TonStorageCli #{client_id:03d}: Session closed, exitcode: {exitcode}", client_id=self.client_id, exitcode=returncode)
        self._proc = None        

    def is_alive(self):
        if self._proc is None:
            return False
        
        return_code = self._proc.poll()
        if return_code is not None:
            logger.error("TonStorageCli #{client_id:03d}: Session aborted, exitcode: {exitcode}", client_id=self.client_id, exitcode=return_code)
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

        raise subprocess.CalledProcessError(self._proc.poll(), self.settings.storage_cli_binary, output=output)
                
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
                    raise subprocess.TimeoutExpired(self.settings.storage_cli_binary, timeout, output=output)
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
                            
        raise subprocess.CalledProcessError(self._proc.poll(), self.settings.storage_cli_binary, 
                                            output=output)

    def _run_command(self, command: str, as_json=True):
        if not self.is_alive():
            self.open()

        try:
            logger.debug("TonStorageCli #{client_id:03d}: CLI run command: {command}", 
                         client_id=self.client_id, command=command)
            response = None
            if as_json:
                self._proc.stdin.write(f'{command} --json\n'.encode())
                self._proc.stdin.flush()
                response = self._read_json(timeout=self.settings.request_timeout, match_error='Query error:')
            else:
                self._proc.stdin.write(f'{command}\n'.encode())
                self._proc.stdin.flush()
                response = self._read_until('Success\n', timeout=self.settings.request_timeout, match_error='Query error:')

            logger.debug("TonStorageCli #{client_id:03d}: CLI got response: {response}", 
                         client_id=self.client_id, response=json.dumps(response))
            return response
        except subprocess.SubprocessError as E:
            self.last_error = E
            self.terminate()
            raise

    def node_get_state(self):
        peers = self.run_get_peers(self.settings.manifest_bag_id)
        if (isinstance(peers, dict) and 'peers' in peers):
            return [
                {
                    'adnl_id': x['adnl_id'], 
                    'ip_str': x['ip_str'], 
                    'adnl': parse_adnl_id(x['adnl_id'])
                }
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

    def run_upload_resume(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'upload-resume {bag_id}', as_json=False) 

    def run_upload_pause(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'upload-pause {bag_id}', as_json=False) 

    def run_get_peers(self, bag_id: str | bytes):
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'get-peers {bag_id}') 

    def run_get(self, bag_id: str | bytes):        
        bag_id = parse_bag_id(bag_id)
        return self._run_command(f'get {bag_id}') 
    
    def run_create(self, path: str, description: str | dict | list = None, copy: bool = False, no_upload : bool = False,
                   check_existance: bool = True):
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
        if no_upload:
            command += '--no-upload '
        command += path
        return self._run_command(command)


def __example():  # pragma: no cover
    cli = TonStorageCli(1,
        TonStorageCliSettings(
            storage_cli_binary="/mnt/c/Work/ton-storage/storage-daemon-cli.exe",
            storage_daemon_addr="172.19.96.1:5555",
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


class TonStorageLru:
    PREV, NEXT, KEY, VALUE = 0, 1, 2, 3   # names for the link fields

    def __init__(self):
        self._lock = RLock()
        self._cache = {}
        self._root = []
        self._root[:] = [self._root, self._root, None, None]
        self._iter_ptr = None

    @property
    def size(self):
        return self._cache.__len__()

    def swap(self):
        with self._lock:
            _cache = self._cache            
            last, first = self._root[TonStorageLru.PREV], self._root[TonStorageLru.NEXT]
            self._root[:] = [self._root, self._root, None, None]
            self._cache = {}
            self._iter_ptr = None

        if  first is last:
            return None, None, None
        else:
            last[TonStorageLru.NEXT] = None
            first[TonStorageLru.PREV] = None
            return last, first, _cache

    def upsert(self, bag_id: str, value: Any = None):        
        with self._lock:
            if bag_id in self._cache:
                item = self._cache[bag_id]
                item[TonStorageLru.VALUE] = value

                item_prev, item_next = item[TonStorageLru.PREV], item[TonStorageLru.NEXT]
                item_prev[TonStorageLru.NEXT] = item_next
                item_next[TonStorageLru.PREV] = item_prev
                last = self._root[TonStorageLru.PREV]            
                last[TonStorageLru.NEXT] = self._root[TonStorageLru.PREV] = item
                item[TonStorageLru.PREV] = last
                item[TonStorageLru.NEXT] = self._root
            else:
                last = self._root[TonStorageLru.PREV]
                item = [last, self._root, bag_id, value]
                last[TonStorageLru.NEXT] = self._root[TonStorageLru.PREV] = self._cache[bag_id] = item

    def upsert_back(self, bag_id: str, value: Any = None):
        with self._lock:
            if bag_id in self._cache:
                return False
            first = self._root[TonStorageLru.NEXT]
            item = [self._root, first, bag_id, value]
            first[TonStorageLru.PREV] = self._root[TonStorageLru.NEXT] = self._cache[bag_id] = item
        return True

    def remove(self, bag_id: str):
        with self._lock:
            item = self._cache.get(bag_id)
            if item is None:
                return None
            del self._cache[bag_id]
            if self._iter_ptr is item:
                self._iter_ptr = item[TonStorageLru.NEXT]
                if self._iter_ptr is self._root:
                    self._iter_ptr = None
            item_prev, item_next = item[TonStorageLru.PREV], item[TonStorageLru.NEXT]
            item_prev[TonStorageLru.NEXT] = item_next
            item_next[TonStorageLru.PREV] = item_prev
        return item[TonStorageLru.VALUE]

    def remove_back(self):
        if self._root[TonStorageLru.NEXT] is self._root[TonStorageLru.PREV]:
            return None, None
        else:
            bag_id = self._root[TonStorageLru.NEXT][TonStorageLru.KEY]
            return bag_id, self.remove(bag_id)

    def __iter__(self):
        self._iter_ptr = self._root
        return self
    
    def __next__(self):
        if self._iter_ptr is None:
            raise StopIteration        
        with self._lock:
            self._iter_ptr = self._iter_ptr[TonStorageLru.NEXT]
            if self._iter_ptr is self._root:
                self._iter_ptr = None
                raise StopIteration
            else:
                return self._iter_ptr[TonStorageLru.KEY], self._iter_ptr[TonStorageLru.VALUE]
            
    def push_back_lru(self, lru):
        nlast, nfirst, ncache = lru.swap()
        if nlast is nfirst:
            return
        with self._lock:
            first = self._root[TonStorageLru.NEXT]
            self._root[TonStorageLru.NEXT] = nfirst
            nfirst[TonStorageLru.PREV] = self._root
            nlast[TonStorageLru.NEXT] = first
            first[TonStorageLru.PREV] = nlast

            for k, item in ncache.items():
                if k in self._cache:
                    item_prev, item_next = item[TonStorageLru.PREV], item[TonStorageLru.NEXT]
                    item_prev[TonStorageLru.NEXT] = item_next
                    item_next[TonStorageLru.PREV] = item_prev
                    del ncache[k]
            self._cache.update(ncache)

            
    
