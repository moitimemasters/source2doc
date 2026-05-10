from fastapi import Request

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import codetour as codetour_storage


async def get_codetour_storage(request: Request) -> codetour_storage.CodetourStorage:
    return request.app.state.codetour_storage


async def get_encryption(request: Request) -> ConfigEncryption:
    return request.app.state.encryption
