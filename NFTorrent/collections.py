from NFTorrent.blockchain.models import PetMemoryNftContent, PetsCollectionInfo
from NFTorrent.modelsbase import CollectionConfig, CollectionInstance, CollectionItemCover

cover = CollectionItemCover(
    baseimage_path="./assets/images/species",
    font="./assets/fonts/Inter_24pt-Bold.ttf",
    subtitle_font="./assets/fonts/Inter_24pt-Regular.ttf",
    title_size=72,
    subtitle_size=40,
    rect_padding=(128, 0),
    rect_fill=(31, 33, 66),
    color="white",
)


config = CollectionConfig(
    collection_info_class=PetsCollectionInfo,
    nft_content_class=PetMemoryNftContent,
    collections=[
        CollectionInstance(
            address="EQAfAC4AUwg_EXRIT0NllzWoZihso8pY_qpPFLKbpMge8JcZ",
            image="./assets/images/collection-logo.webp",
            item_cover=cover,
            meta={
                "name": "Pets Memorial - 1",
                "description": "Transform your memories into living digital artifacts — timeless, immutable and authentic, powered by blockchain technology. Share your story with those who'll truly understand, inspire others, and preserve what matters most in a world where nothing truly disappears.\nBecause some stories are too precious to remain just another photo in your smartphone gallery.",
                "attributes": [],
            },
            nft_samples={},
        ),
    ],
)

__all__ = ["config"]
