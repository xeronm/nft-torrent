from NFTorrent.models import NftCollection
from NFTorrent.messages import PetMemoryNftContent

collections = [
    NftCollection(
        PetMemoryNftContent, 
        'EQBAIrKhrZI5BIOmwrHiZ__QRICiFWJR_HRH5Wer3fd1f-lR', 
        './assets/images/collection.webp'
    ),
    NftCollection(
        PetMemoryNftContent, 
        'EQBOdDO6iszbtbR0YnOz2IHk2eP6cCVKqkl7vRvoEtwa83lU', 
        './assets/images/collection.webp'
    )
]