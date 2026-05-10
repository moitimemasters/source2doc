"""Shared pytest fixtures for gateway integration tests.

Builds a FastAPI app the same way ``app.app:create_app`` does but bypasses
the production lifespan: PostgreSQL and S3 are replaced with ``AsyncMock``
stubs and Redis is replaced with ``fakeredis``. The result is a self-
contained test that exercises the real route handlers, encryption, and
Redis-stream contract without external services.
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
        # Admin auth fields became required upstream — supply throwaway values.
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
    """Stand-in for source2doc.storage.PostgresStorage."""
    storage = MagicMock()
    storage.get_repository = AsyncMock(return_value=None)
    storage.create_repository = AsyncMock(return_value=None)
    storage.list_repositories = AsyncMock(return_value=[])
    storage.delete_repository = AsyncMock(return_value=None)
    storage.list_bundles = AsyncMock(return_value=[])
    storage.get_index = AsyncMock(return_value=None)
    storage.get_bundle_pages = AsyncMock(return_value=[])
    storage.get_page = AsyncMock(return_value=None)
    storage.get_bundle_repository = AsyncMock(return_value=None)
    storage.get_page_repository = AsyncMock(return_value=None)  # B6.5
    storage.get_dominant_model = AsyncMock(return_value=None)
    storage.list_bundle_generation_ids_for_repo = AsyncMock(return_value=[])
    storage.get_metrics_for_generation = AsyncMock(return_value=[])
    storage.get_metrics_aggregate = AsyncMock(
        return_value={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": None,
        }
    )
    # B3.4 — admin metrics dashboard buckets.
    storage.get_metrics_buckets = AsyncMock(return_value=[])
    # B6.2 — cross-page symbol index.
    storage.record_page_symbols = AsyncMock(return_value=None)
    storage.lookup_page_for_symbol = AsyncMock(return_value=None)
    storage.list_page_symbols = AsyncMock(return_value=[])
    # B11.2 — append-only page version history.
    storage.record_page_version = AsyncMock(return_value=None)
    storage.list_page_versions = AsyncMock(return_value=[])
    storage.get_page_version = AsyncMock(return_value=None)
    # B13.2 — page-link graph.
    storage.record_page_links = AsyncMock(return_value=None)
    storage.list_page_links = AsyncMock(return_value=[])
    storage.list_inbound_links = AsyncMock(return_value=[])
    # B13.4 — diagnostic trace endpoint.
    storage.find_generations_by_trace_id = AsyncMock(return_value=[])
    storage.get_metrics_by_trace_id = AsyncMock(return_value=[])
    # Migration 20 — Pydantic-AI agent run history.
    storage.record_agent_run = AsyncMock(return_value=1)
    storage.list_agent_runs = AsyncMock(return_value=[])
    storage.get_agent_run = AsyncMock(return_value=None)
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
    """Construct a FastAPI app with stubbed lifecycle.

    We deliberately replace the real lifespan with one that wires the
    pre-built fakes onto ``app.state``. All route handlers reach for
    ``app.state.redis`` / ``app.state.storage`` / ``app.state.encryption``
    via dependency injection, so this is sufficient to exercise them.
    """

    # Preset storage stub: returns None for both lookups, which forces the
    # preset_resolver to fall back to request-supplied LLM/embeddings configs.
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

    # Build a fresh app to avoid leaking state across tests.
    from app.errors import register as register_errors
    from app.routes.admin.health.router import router as admin_health_router
    from app.routes.admin.trace.router import router as admin_trace_router
    from app.routes.bundles.router import router as bundles_router
    from app.routes.codetours.router import router as codetours_router
    from app.routes.docs.router import router as docs_router
    from app.routes.generations.router import router as generations_router
    from app.routes.health import router as health_router
    from app.routes.logs.router import router as logs_router
    from app.routes.repos.router import router as repos_router
    from app.routes.metrics.router import router as metrics_router
    from app.routes.search.router import router as search_router
    from app.routes.streams.router import router as streams_router
    from app.routes.tasks.resume import router as tasks_resume_router
    from app.routes.tasks.retry import router as tasks_retry_router
    from app.routes.tasks.router import router as tasks_router
    from app.routes.tasks.stop import router as tasks_stop_router
    from app.routes.wiki.router import router as wiki_router

    app = FastAPI(lifespan=stub_lifespan)
    app.state.config = fake_config
    register_errors(app)
    app.include_router(health_router)
    app.include_router(streams_router)
    app.include_router(logs_router)
    app.include_router(docs_router)
    app.include_router(wiki_router)
    app.include_router(tasks_router)
    app.include_router(tasks_retry_router)
    app.include_router(tasks_resume_router)
    app.include_router(tasks_stop_router)
    app.include_router(repos_router)
    app.include_router(search_router)
    app.include_router(bundles_router)
    app.include_router(codetours_router)
    app.include_router(generations_router)
    app.include_router(metrics_router)
    app.include_router(admin_health_router)
    app.include_router(admin_trace_router)

    # Override the get_config dependency so handlers read the test config.
    from app.config import get_config

    app.dependency_overrides[get_config] = lambda: fake_config

    # Routes that mutate state (POST /tasks, /repos/clone, /repos/upload,
    # DELETE /repos/{id}) gained a `Depends(require_admin)` upstream.
    # Bypass it: hand back a fake AdminSession so the protected handlers run.
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
    # raise_app_exceptions=False lets registered FastAPI exception handlers
    # convert errors to HTTP responses instead of bubbling them to the test.
    transport = ASGITransport(app=app_under_test, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with app_under_test.router.lifespan_context(app_under_test):
            yield c
