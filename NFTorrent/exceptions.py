from typing import Any, Dict
from fastapi.exceptions import HTTPException
from fastapi import status

from NFTorrent.address import parse_bag_id

class TorrentFileNotFound(HTTPException):

    def __init__(self, detail: Any = None):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
                         detail=detail or 'Torrent File not found')
      

class TorrentForbidden(HTTPException):

    def __init__(self, detail: Any = None):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, 
                         detail=detail or 'Operation forbidden')
        

class TorrentStorageError(HTTPException):

    def __init__(self, detail: Any = None):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, 
                         detail=detail or 'Storage daemon error')


class TorrentClientError(HTTPException):    

    def __init__(self, detail: Any = None, status_code: int = status.HTTP_502_BAD_GATEWAY):
        super().__init__(status_code=status_code, 
                         detail=detail or 'Storage client error')        

    @classmethod
    def get_errors(cls, result):
        error = result.get('error', None)
        return error

    @classmethod
    def from_response(cls, response):
        if not isinstance(response, dict):
            return response
        error = response.get('error', None)
        if error is None:
            return response

        if error == TorrentNotFound.client_message:
            raise TorrentNotFound()
        elif error.startswith(TorrentDuplicateHash.client_message):
            raise TorrentDuplicateHash(bag_id=parse_bag_id(error[len(TorrentDuplicateHash.client_message):]))
        else:
            raise TorrentClientError(error)

class TorrentNotFound(TorrentClientError):
    client_message = 'Query error: No such torrent'

    def __init__(self):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, 
                         detail='No such torrent')


class TorrentDuplicateHash(TorrentClientError):
    client_message = 'Query error: Cannot add torrent: duplicate hash '

    def __init__(self, bag_id: str = None):
        super().__init__(status_code=status.HTTP_409_CONFLICT, 
                         detail='Cannot add torrent: duplicate hash')
        self.bag_id = bag_id
