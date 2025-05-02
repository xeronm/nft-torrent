from NFTorrent.blockchain.models import PetMemoryNftContent, PetsCollectionInfo
from NFTorrent.dbmodels import PetMemoryNft, PetsCollection
from NFTorrent.modelsbase import CollectionConfig, CollectionInstance

config = CollectionConfig(
    collection_info_class=PetsCollectionInfo,
    nft_content_class=PetMemoryNftContent,
    dbmodel_class=PetsCollection,
    dbmodel_nft_class=PetMemoryNft,
    collections=[
        CollectionInstance(
            address='EQBAIrKhrZI5BIOmwrHiZ__QRICiFWJR_HRH5Wer3fd1f-lR',
            image='./assets/images/collection-3.webp'
        ),
        CollectionInstance(
            address='EQBOdDO6iszbtbR0YnOz2IHk2eP6cCVKqkl7vRvoEtwa83lU',
            image='./assets/images/collection-3.webp'
        )
    ]
)

__all__ = ['config']
