from typing import Any, Dict
from fastapi.exceptions import HTTPException
from fastapi import status

class TorrentPathNotFound(HTTPException):

    def __init__(self, detail: Any = None):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
                         detail=detail or 'Specified path not found in torrent')


class TorrentNotFound(HTTPException):

    def __init__(self, detail: Any = None):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, 
                         detail=detail or 'Torrent not found')
        

class TorrentForbidden(HTTPException):

    def __init__(self, detail: Any = None):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, 
                         detail=detail or 'Operation forbidden')
        

class TorrentStorageError(HTTPException):

    def __init__(self, detail: Any = None):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, 
                         detail=detail or 'Storage daemon error')


class TorrentClientError(HTTPException):    

    def __init__(self, result: Dict):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, 
                         detail=result.get('error') or 'Client communication error')        