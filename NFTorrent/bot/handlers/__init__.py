from . import admin, inquiry, nft

routers = [inquiry.router, nft.router, admin.router]

__all__ = ["routers"]
