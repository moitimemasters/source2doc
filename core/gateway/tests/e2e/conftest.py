"""E2E test fixtures: spin up real Postgres + Redis via testcontainers.

These tests are SLOW (container boot ~2-5s each, schema load on top) so
they live behind the ``@pytest.mark.e2e`` marker. The default ``pytest``
invocation skips them; CI / local runs use ``pytest -m e2e`` or
``RUN_E2E=1 pytest``.

Containers are session-scoped — boot once, reuse across all e2e tests.
Each test gets a fresh app instance + truncated tables / cleared streams.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.localstack import LocalStackContainer
from testcontainers.postgres import PostgresContainer

from source2doc.config import PostgresConfig, QdrantConfig, RedisConfig, S3Config
from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage import codetour as codetour_storage

from app.config import Config


# Walk: e2e/conftest.py -> e2e -> tests -> gateway -> core -> source2docinfra
MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"


@pytest.fixture(scope="session")
def docker_host_env() -> None:
    """Point testcontainers at the Colima Docker socket if present.

    Colima ships its own socket at ``~/.colima/default/docker.sock``; the
    Docker CLI uses it via context, but the testcontainers Python client
    relies on the ``DOCKER_HOST`` env var.
    """

    if "DOCKER_HOST" in os.environ:
        return
    candidate = Path.home() / ".colima" / "default" / "docker.sock"
    if candidate.exists():
        os.environ["DOCKER_HOST"] = f"unix://{candidate}"
    # Disable Ryuk reaper (it can struggle on Colima).
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture(scope="session")
def postgres_container(docker_host_env: None) -> Any:
    # PostgresContainer's built-in readiness check returns before the host
    # port is actually reachable through Colima's port-forwarder. Drive a
    # raw DockerContainer ourselves and wait for the "ready to accept"
    # log line — same recipe as redis_container below. Username/password/db
    # match the docker-compose role so migrations/*.sql GRANTs resolve.
    container = (
        DockerContainer("postgres:16-alpine")
        .with_env("POSTGRES_USER", "docgen")
        .with_env("POSTGRES_PASSWORD", "docgen_password")
        .with_env("POSTGRES_DB", "docgen")
        .with_exposed_ports(5432)
    )
    with container as pg:
        wait_for_logs(
            pg,
            "database system is ready to accept connections",
            timeout=60,
        )
        yield pg


@pytest.fixture(scope="session")
def redis_container(docker_host_env: None) -> Any:
    # The packaged RedisContainer wraps a deprecated `wait_container_is_ready`
    # decorator that swallows boot failures on Colima. Drive the raw
    # DockerContainer ourselves so any boot/wait failure surfaces loudly.
    container = DockerContainer("redis:7-alpine").with_exposed_ports(6379)
    with container as r:
        wait_for_logs(r, "Ready to accept connections", timeout=60)
        yield r


@pytest.fixture(scope="session")
def localstack_container(docker_host_env: None) -> Any:
    """LocalStack S3 container — only the s3 service to keep boot time low."""
    container = LocalStackContainer(image="localstack/localstack:3").with_services("s3")
    with container as ls:
        yield ls


@pytest.fixture(scope="session")
def s3_endpoint_url(localstack_container: Any) -> str:
    """Host-reachable URL for the LocalStack S3 endpoint."""
    return localstack_container.get_url()


@pytest.fixture
def s3_bucket(s3_endpoint_url: str) -> str:
    """Create the source2doc-repos bucket per test (idempotent if exists)."""
    import boto3
    from botocore.config import Config as BotoConfig

    bucket = "source2doc-repos"
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
        config=BotoConfig(signature_version="s3v4"),
    )
    try:
        client.create_bucket(Bucket=bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except client.exceptions.BucketAlreadyExists:
        pass
    # Empty bucket between tests so each starts clean.
    objects = client.list_objects_v2(Bucket=bucket).get("Contents", []) or []
    for obj in objects:
        client.delete_object(Bucket=bucket, Key=obj["Key"])
    return bucket


@pytest.fixture(scope="session")
def postgres_dsn(postgres_container: Any) -> str:
    """asyncpg-compatible DSN built from the raw DockerContainer."""
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    if host == "localhost":
        # Force IPv4 — same happy-eyeballs race as Redis.
        host = "127.0.0.1"
    return f"postgresql://docgen:docgen_password@{host}:{port}/docgen"


@pytest.fixture(scope="session")
def redis_url(redis_container: Any) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    # Force IPv4 — happy-eyeballs DNS races give intermittent connect refused
    # on Colima when the asyncio loop tries ::1 first.
    if host in ("localhost",):
        host = "127.0.0.1"
    return f"redis://{host}:{port}/0"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def applied_schema(postgres_dsn: str) -> str:
    """Apply migrations/*.sql in order against the fresh container."""

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, f"no migrations found in {MIGRATIONS_DIR}"

    conn = await _connect_with_retry(postgres_dsn)
    try:
        for sql_file in files:
            await conn.execute(sql_file.read_text(encoding="utf-8"))
    finally:
        await conn.close()

    return postgres_dsn


async def _connect_with_retry(dsn: str, attempts: int = 30) -> Any:
    """Retry asyncpg.connect to ride out Colima's port-forward race."""
    import asyncio as _asyncio

    last: Exception | None = None
    for _ in range(attempts):
        try:
            return await asyncpg.connect(dsn)
        except (ConnectionRefusedError, OSError) as exc:
            last = exc
            await _asyncio.sleep(0.5)
    raise RuntimeError(f"Could not connect to Postgres at {dsn}") from last


@pytest_asyncio.fixture
async def clean_db(applied_schema: str) -> AsyncIterator[str]:
    """Truncate all data tables before each test so they are independent."""

    conn = await _connect_with_retry(applied_schema)
    try:
        # Discover all tables in the public schema and truncate them in one shot.
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        if rows:
            tables = ", ".join(f'"{r["tablename"]}"' for r in rows)
            await conn.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    yield applied_schema


@pytest_asyncio.fixture
async def clean_redis(redis_url: str) -> AsyncIterator[str]:
    # Retry: when LocalStack and Postgres also boot in this session, the
    # asyncio Redis client occasionally races Colima's port-forwarder and
    # the first connect refuses. A few short retries hide that flake.
    import asyncio as _asyncio

    last_exc: Exception | None = None
    r: Any = None
    for _ in range(20):
        try:
            r = aioredis.from_url(redis_url, decode_responses=True)
            await r.ping()
            await r.flushdb()
            break
        except Exception as exc:
            last_exc = exc
            if r is not None:
                await r.aclose()
                r = None
            await _asyncio.sleep(0.5)
    else:
        raise RuntimeError(
            f"Redis container not reachable at {redis_url}"
        ) from last_exc

    yield redis_url
    if r is not None:
        await r.aclose()


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def real_config(
    clean_db: str,
    clean_redis: str,
    encryption_key: str,
    request: pytest.FixtureRequest,
) -> Config:
    """Build an app.config.Config that points at the live containers.

    PostgresConfig requires individual host/port/user/password fields.  We
    parse them out of the asyncpg DSN that testcontainers produced.

    If a ``s3_endpoint_url`` fixture is in scope (i.e., the test pulled it
    in), wire S3 to that LocalStack URL — otherwise leave the default so
    tests that don't touch S3 don't pay the LocalStack boot cost.
    """

    from urllib.parse import urlparse

    parsed = urlparse(clean_db)
    pg = PostgresConfig(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        database=(parsed.path or "/test").lstrip("/"),
        user=parsed.username or "test",
        password=parsed.password or "test",
    )

    s3_endpoint = "http://localhost:4566"
    if "s3_endpoint_url" in request.fixturenames:
        s3_endpoint = request.getfixturevalue("s3_endpoint_url")

    return Config(
        debug=True,
        encryption_key=encryption_key,
        # Admin auth fields became required upstream — supply throwaway values.
        admin_username="test-admin",
        admin_password_hash="$2b$12$abcdefghijklmnopqrstuv",
        cookie_secure=False,
        redis=RedisConfig(url=clean_redis, stream_prefix="events"),
        postgres=pg,
        qdrant=QdrantConfig(),
        s3=S3Config(
            endpoint_url=s3_endpoint,
            access_key_id="test",
            secret_access_key="test",
            region="us-east-1",
            bucket="source2doc-repos",
        ),
    )


@pytest_asyncio.fixture
async def real_app(real_config: Config) -> AsyncIterator[FastAPI]:
    """Spin up the FastAPI app against the real containers."""

    from app.errors import register as register_errors
    from app.routes.bundles.router import router as bundles_router
    from app.routes.codetours.router import router as codetours_router
    from app.routes.docs.router import router as docs_router
    from app.routes.logs.router import router as logs_router
    from app.routes.repos.router import router as repos_router
    from app.routes.streams.router import router as streams_router
    from app.routes.tasks.router import router as tasks_router

    from source2doc.storage.admin_sessions import AdminSessionStorage
    from source2doc.storage.presets import ConfigPresetStorage

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        app_.state.redis = await aioredis.from_url(
            real_config.redis.url, decode_responses=True
        )
        app_.state.storage = PostgresStorage(real_config.postgres.connection_string)
        await app_.state.storage.connect()
        app_.state.codetour_storage = codetour_storage.CodetourStorage(
            real_config.postgres.connection_string
        )
        await app_.state.codetour_storage.connect()
        app_.state.preset_storage = ConfigPresetStorage(real_config.postgres.connection_string)
        await app_.state.preset_storage.connect()
        app_.state.admin_sessions = AdminSessionStorage(real_config.postgres.connection_string)
        await app_.state.admin_sessions.connect()
        app_.state.encryption = ConfigEncryption(real_config.encryption_key)
        try:
            yield
        finally:
            await app_.state.redis.aclose()
            await app_.state.storage.close()
            await app_.state.codetour_storage.close()
            await app_.state.preset_storage.close()
            await app_.state.admin_sessions.close()

    app = FastAPI(lifespan=lifespan)
    app.state.config = real_config
    register_errors(app)
    app.include_router(streams_router)
    app.include_router(logs_router)
    app.include_router(docs_router)
    app.include_router(tasks_router)
    app.include_router(repos_router)
    app.include_router(bundles_router)
    app.include_router(codetours_router)

    from app.config import get_config

    app.dependency_overrides[get_config] = lambda: real_config

    # Bypass admin auth — POST routes (tasks, repos/clone, repos/upload,
    # DELETE repos/{id}) gained Depends(require_admin) upstream.
    from app.security.admin import require_admin
    from source2doc.storage.admin_sessions import AdminSession
    from datetime import UTC, datetime, timedelta

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
async def real_client(real_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=real_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with real_app.router.lifespan_context(real_app):
            yield c
