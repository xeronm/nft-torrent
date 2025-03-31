from typing import List
from dataclasses import dataclass

from pyTON.manager import TonlibManager as _TonlibManager
from pytonlib.utils.tokens import parse_nft_item_data
from pytonlib.utils.address import detect_address
from pytonlib import TonlibError
from fastapi.exceptions import HTTPException
from fastapi import status
from tonpy.types import CellSlice

from NFTorrent.messages import TvmStructure

@dataclass
class NftCollection:
    address: str
    nft_content_class: TvmStructure

class TonlibManager(_TonlibManager):

    def __init__(self, *args, nft_collections: List[NftCollection] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.nft_collections = { detect_address(x.address)['raw_form']: x for x in nft_collections }

    def get_nft_collection(self, address: str) -> NftCollection:
        return self.nft_collections.get(detect_address(address)['raw_form'])

    async def get_nft_item_address(self, collection_address, item_index):
        method = 'get_nft_item_address'
        try:
            addr = await self.dispatch_request(method, collection_address, item_index)
        except TonlibError:
            addr = await self.dispatch_archival_request(method, collection_address, item_index)
        return addr    

    async def get_nft_data(self, address: str, skip_verification: bool = False):
        nft_data_result = await self.raw_run_method(address, 'get_nft_data', [], None)
        if nft_data_result['stack'] is None or len(nft_data_result['stack']) != 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Smart contract is not NFT")
        
        nft_data = parse_nft_item_data(nft_data_result['stack'])

        nft_collection = None
        if nft_data['collection_address'] is not None:
            nft_collection = self.get_nft_collection(nft_data['collection_address'])
        if nft_collection is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="NFT collection not known")

        if not skip_verification:
            verified_nft_address = await self.get_nft_item_address(nft_data['collection_address'], nft_data['index'])
            if detect_address(verified_nft_address)['raw_form'] != detect_address(address)['raw_form']:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification with NFT collection failed")

        print(nft_data['individual_content'])
        nft_data['individual_content'] = nft_collection.nft_content_class(CellSlice(nft_data['individual_content']))

        return nft_data        
    

    def setup_cache(self):
        pass    