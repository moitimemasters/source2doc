from fastapi import Request
import redis.asyncio as aioredis

from source2doc.storage import PostgresStorage


async def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


async def get_storage(request: Request) -> PostgresStorage:
    return request.app.state.storage
