from fastapi import Request

from source2doc.storage import PostgresStorage


async def get_storage(request: Request) -> PostgresStorage:
    return request.app.state.storage
