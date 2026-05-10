from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
import redis.asyncio as aioredis

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage import codetour as codetour_storage
from source2doc.storage.admin_sessions import AdminSessionStorage
from source2doc.storage.presets import ConfigPresetStorage

from app.config import Config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config: Config = app.state.config

    app.state.redis = await aioredis.from_url(
        config.redis.url,
        decode_responses=True,
    )

    app.state.storage = PostgresStorage(
        config.postgres.connection_string,
        pool_min_size=config.postgres.pool_min_size,
        pool_max_size=config.postgres.pool_max_size,
    )
    await app.state.storage.connect()

    app.state.codetour_storage = codetour_storage.CodetourStorage(config.postgres.connection_string)
    await app.state.codetour_storage.connect()

    app.state.preset_storage = ConfigPresetStorage(config.postgres.connection_string)
    await app.state.preset_storage.connect()

    app.state.admin_sessions = AdminSessionStorage(config.postgres.connection_string)
    await app.state.admin_sessions.connect()

    app.state.encryption = ConfigEncryption(config.encryption_key)

    yield

    await app.state.redis.aclose()
    await app.state.storage.close()
    await app.state.codetour_storage.close()
    await app.state.preset_storage.close()
    await app.state.admin_sessions.close()
