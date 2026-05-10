from fastapi import Request

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.prdoc import PRDocStorage


async def get_prdoc_storage(request: Request) -> PRDocStorage:
    return request.app.state.prdoc_storage


async def get_encryption(request: Request) -> ConfigEncryption:
    return request.app.state.encryption
