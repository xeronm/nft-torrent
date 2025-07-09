from . import inquiry
from . import nft

routers = [
    inquiry.router,
    nft.router
]

__all__ = ["routers"]

