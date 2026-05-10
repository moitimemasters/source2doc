"""Perf-suite fixtures.

Reuses the in-process FastAPI + fakeredis app harness from
``tests/conftest.py`` so latency benchmarks don't need real Postgres /
Redis / S3. These tests target the gateway code path between request and
response — the only stateful dependency they truly need is Redis, which
is faked.

PMI-mapping: СКН-01 (status query latency), СКН-02 (push event latency).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from cryptography.fernet import Fernet
import fakeredis.aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio

from source2doc.config import PostgresConfig, QdrantConfig, RedisConfig, S3Config
from source2doc.security.encryption import ConfigEncryption

from app.config import Config


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def fake_config(encryption_key: str) -> Config:
    return Config(
        debug=True,
        encryption_key=encryption_key,
        admin_username="test-admin",
        admin_password_hash="$2b$12$abcdefghijklmnopqrstuv",
        cookie_secure=False,
        redis=RedisConfig(
            url="redis://localhost",
            stream_prefix="events",
        ),
        postgres=PostgresConfig(),
        qdrant=QdrantConfig(),
        s3=S3Config(),
    )


@pytest.fixture
def fake_storage() -> MagicMock:
    storage = MagicMock()
    storage.get_repository = AsyncMock(return_value=None)
    storage.create_repository = AsyncMock(return_value=None)
    storage.list_repositories = AsyncMock(return_value=[])
    storage.delete_repository = AsyncMock(return_value=None)
    storage.list_bundles = AsyncMock(return_value=[])
    storage.get_index = AsyncMock(return_value=None)
    storage.get_bundle_pages = AsyncMock(return_value=[])
    storage.get_page = AsyncMock(return_value=None)
    return storage


@pytest.fixture
def fake_codetour_storage() -> MagicMock:
    storage = MagicMock()
    storage.create_pending_tour = AsyncMock(return_value=None)
    storage.get_codetour = AsyncMock(return_value=None)
    storage.list_codetours_by_generation = AsyncMock(return_value=[])
    storage.list_all_codetours = AsyncMock(return_value=[])
    storage.mark_cancelled = AsyncMock(return_value=None)
    return storage


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[Any]:
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def app_under_test(
    fake_config: Config,
    fake_storage: MagicMock,
    fake_codetour_storage: MagicMock,
    fake_redis: Any,
) -> AsyncIterator[FastAPI]:
    fake_preset_storage = MagicMock()
    fake_preset_storage.get_by_name = AsyncMock(return_value=None)
    fake_preset_storage.get_default = AsyncMock(return_value=None)

    fake_admin_sessions = MagicMock()

    @asynccontextmanager
    async def stub_lifespan(_app: FastAPI):
        _app.state.redis = fake_redis
        _app.state.storage = fake_storage
        _app.state.codetour_storage = fake_codetour_storage
        _app.state.preset_storage = fake_preset_storage
        _app.state.admin_sessions = fake_admin_sessions
        _app.state.encryption = ConfigEncryption(fake_config.encryption_key)
        yield

    from app.errors import register as register_errors
    from app.routes.bundles.router import router as bundles_router
    from app.routes.codetours.router import router as codetours_router
    from app.routes.docs.router import router as docs_router
    from app.routes.logs.router import router as logs_router
    from app.routes.repos.router import router as repos_router
    from app.routes.streams.router import router as streams_router
    from app.routes.tasks.router import router as tasks_router

    app = FastAPI(lifespan=stub_lifespan)
    app.state.config = fake_config
    register_errors(app)
    app.include_router(streams_router)
    app.include_router(logs_router)
    app.include_router(docs_router)
    app.include_router(tasks_router)
    app.include_router(repos_router)
    app.include_router(bundles_router)
    app.include_router(codetours_router)

    from app.config import get_config

    app.dependency_overrides[get_config] = lambda: fake_config

    from datetime import UTC, datetime, timedelta

    from source2doc.storage.admin_sessions import AdminSession

    from app.security.admin import require_admin

    now = datetime.now(UTC)
    fake_session = AdminSession(
        token_hash="test-token-hash",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        last_seen_at=now,
    )
    app.dependency_overrides[require_admin] = lambda: fake_session

    yield app


@pytest_asyncio.fixture
async def client(app_under_test: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_under_test, raise_app_exceptions=False)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as c,
        app_under_test.router.lifespan_context(app_under_test),
    ):
        yield c
