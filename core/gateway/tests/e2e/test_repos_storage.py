"""End-to-end tests for /api/v1/repos against real Postgres + Redis.

Covers PMI 6.3.2, 6.3.3, 6.3.11. Asserts that:
  * the gateway writes a repository row that can be re-fetched via
    ``GET /api/v1/repos`` and ``GET /api/v1/repos/{id}``,
  * the clone task lands on the ``tasks:repos`` Redis Stream,
  * delete removes the row from the database.
"""

import json
from typing import Any

import asyncpg
import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient


pytestmark = pytest.mark.e2e


async def test_clone_persists_repo_to_postgres(
    real_client: AsyncClient,
    real_config: Any,
) -> None:
    response = await real_client.post(
        "/api/v1/repos/clone",
        json={"git_url": "https://github.com/example/foo.git", "branch": "main"},
    )
    assert response.status_code == 200, response.text
    repo_id = response.json()["repo_id"]

    conn = await asyncpg.connect(real_config.postgres.connection_string)
    try:
        row = await conn.fetchrow(
            "SELECT name, source_type, git_url, git_branch FROM repositories WHERE repo_id = $1",
            repo_id,
        )
    finally:
        await conn.close()

    assert row is not None
    assert row["source_type"] == "git"
    assert row["git_url"] == "https://github.com/example/foo.git"
    assert row["git_branch"] == "main"
    assert row["name"] == "foo"


async def test_clone_publishes_to_real_redis_stream(
    real_client: AsyncClient,
    real_config: Any,
) -> None:
    response = await real_client.post(
        "/api/v1/repos/clone",
        json={"git_url": "https://github.com/example/bar.git"},
    )
    assert response.status_code == 200

    r = aioredis.from_url(real_config.redis.url, decode_responses=True)
    try:
        entries = await r.xrange("tasks:repos", "-", "+")
    finally:
        await r.aclose()

    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["type"] == "repo.clone_requested"
    data = json.loads(fields["data"])
    assert data["source_type"] == "git"
    assert data["source_data"]["url"] == "https://github.com/example/bar.git"


async def test_list_and_get_repository_round_trip(
    real_client: AsyncClient,
) -> None:
    create = await real_client.post(
        "/api/v1/repos/clone",
        json={"git_url": "https://github.com/example/baz.git", "name": "baz-renamed"},
    )
    repo_id = create.json()["repo_id"]

    listing = await real_client.get("/api/v1/repos")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["repositories"][0]["name"] == "baz-renamed"

    detail = await real_client.get(f"/api/v1/repos/{repo_id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "baz-renamed"
    assert detail.json()["git_url"] == "https://github.com/example/baz.git"


async def test_get_repository_404_for_unknown(real_client: AsyncClient) -> None:
    response = await real_client.get("/api/v1/repos/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_delete_route_drops_db_row_even_when_s3_missing(
    real_client: AsyncClient,
) -> None:
    """Stale rows whose S3 archive vanished must still be deletable so the
    admin UI can clean them up (audit Bug 19). Postgres existence is the
    source of truth — S3 cleanup is best-effort. The clone task creates the
    row but no archive lands in S3 in the test environment, so this is the
    "stale row" path."""

    create = await real_client.post(
        "/api/v1/repos/clone",
        json={"git_url": "https://github.com/example/qux.git"},
    )
    repo_id = create.json()["repo_id"]

    response = await real_client.delete(f"/api/v1/repos/{repo_id}")
    assert response.status_code == 200, response.text

    follow_up = await real_client.get(f"/api/v1/repos/{repo_id}")
    assert follow_up.status_code == 404
