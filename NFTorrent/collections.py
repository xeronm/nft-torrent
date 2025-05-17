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
            address='EQCq3q4Oi6nxLGA399SXlUv6XR8sAECm_TPIl-kZRY6rvIvc',
            image='./assets/images/collection-3.webp'
        ),
    ]
)

__all__ = ['config']
