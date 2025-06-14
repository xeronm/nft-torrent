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
            address="EQAI_6RBqCUCGlNKRQOh_diuz8az2S_TY3IAHdozFTDDGs-9",
            image="./assets/images/collection-3.webp",
            meta={
                "name": "Pets Memorial - 1",
                "description": "Transform your memories into living digital artifacts — timeless, immutable and authentic, powered by blockchain technology. Share your story with those who'll truly understand, inspire others, and preserve what matters most in a world where nothing truly disappears.\nBecause some stories are too precious to remain just another photo in your smartphone gallery.",
                "attributes": [],
            },
            nft_samples={
                "image_url": "UQDGmyLShGRLKLTvXT027DQGmIQ5K-FU7U0ULuGsnVRKLGg9",
                "image_onchain": "UQBI_r486VLTnscs7SQNE29vETuHajF0mxwpGu57VzSLwPnY",
                "image_ipfs": "UQCckh6snB2Yvl7fPY8Jy-fVKEFPMPCY16kRcm7868JVPvOZ",
            },
        ),
        CollectionInstance(
            address="EQDXmMnHdy75YldKGYfpm2eGTbkpHRq6CLjVIOJBdgjQt_Z9",
            image="./assets/images/collection-3.webp",
            meta={
                "name": "Pets Memorial - 2",
                "description": "Transform your memories into living digital artifacts — timeless, immutable and authentic, powered by blockchain technology. Share your story with those who'll truly understand, inspire others, and preserve what matters most in a world where nothing truly disappears.\nBecause some stories are too precious to remain just another photo in your smartphone gallery.",
                "attributes": [],
            },
            nft_samples={
                "image_ipfs": "EQAM38nXYgpT-3jFCpKai2aAZF0CuqZyeiH2F13lsKjl77KO",
            },
        ),
    ],
)

__all__ = ["config"]
