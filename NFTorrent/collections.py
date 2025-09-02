from NFTorrent.blockchain.models import PetMemoryNftContent, PetsCollectionInfo
from NFTorrent.modelsbase import CollectionConfig, CollectionInstance, CollectionItemCover

cover = CollectionItemCover(
    baseimage_path="./assets/images/species",
    font="./assets/fonts/Inter_24pt-Bold.ttf",
    subtitle_font="./assets/fonts/Inter_24pt-Regular.ttf",
    title_size=36,
    subtitle_size=20,
    rect_padding=(96, 0),
    rect_fill=(31, 33, 66),
    color="white",
)


config = CollectionConfig(
    collection_info_class=PetsCollectionInfo,
    nft_content_class=PetMemoryNftContent,
    collections=[
        CollectionInstance(
            address="EQD7HAmDSSxSXJNhAWod8suE-_W0iwlC9o_OUR76kXo3jrtD",
            image="./assets/images/collection-logo.webp",
            item_cover=cover,
            meta={
                "name": "Pets Memorial (Test)",
                "description": "Pets Memorial is an NFT collection that lets you create a lasting digital tribute to your beloved pet. Turn photos and memories into unique NFTs that preserve their story on the blockchain. Share your tribute with others who understand and keep your pet’s memory alive.\nhttps://t.me/pets_memorial_bot",
                "attributes": [],
            },
            nft_samples={},
        ),
    ],
)

__all__ = ["config"]
