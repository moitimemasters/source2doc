"""Unit tests for ``PostgresStorage`` page-version helpers (B11.2 / ТЗ ГЕН-08).

These tests stub the asyncpg connection so they run without a real
Postgres — the e2e round-trip lives in
``core/gateway/tests/e2e/test_storage_round_trip.py`` and exercises the
same code path against a real instance.

What we pin down here:

  * ``record_page_version`` issues a single INSERT … ON CONFLICT and
    serialises ``body`` / ``metadata`` as JSON.
  * ``list_page_versions`` / ``get_page_version`` decode JSONB back to
    dicts (asyncpg can return either ``str`` or ``dict`` depending on
    codec setup — we handle both).
  * The dataclasses survive round-tripping the underlying row shape.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from source2doc.storage import PostgresStorage
from source2doc.storage.postgres import PageVersionDetail, PageVersionMeta


PAGE_ID = "overview"
GEN_ID = UUID("11111111-2222-3333-4444-555555555555")
REPO_ID = UUID("22222222-3333-4444-5555-666666666666")


def _make_storage_with_conn(conn: MagicMock) -> PostgresStorage:
    """Build a ``PostgresStorage`` with a mock pool yielding ``conn``."""
    pool = MagicMock()

    @asynccontextmanager
    async def acquire():
        yield conn

    pool.acquire = acquire
    storage = PostgresStorage(connection_string="postgres://stub")
    storage.pool = pool
    return storage


@pytest.mark.asyncio
async def test_record_page_version_serialises_body_and_metadata_as_json() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    storage = _make_storage_with_conn(conn)

    body = {
        "title": "Overview",
        "summary": "Sum",
        "blocks": [{"type": "paragraph", "text": "hi"}],
        "related": ["intro"],
    }
    metadata = {"tags": ["v1"], "reading_time": 1}
    await storage.record_page_version(
        page_id=PAGE_ID,
        generation_id=GEN_ID,
        repository_id=REPO_ID,
        commit_sha="abc1234",
        body=body,
        body_markdown="# Overview\n",
        metadata=metadata,
    )

    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args
    sql = args[0]
    assert "INSERT INTO page_versions" in sql
    assert "ON CONFLICT (page_id, generation_id) DO UPDATE" in sql

    # Bound parameters: page_id, gen, repo, sha, body_json, md, meta_json
    assert args[1] == PAGE_ID
    assert args[2] == GEN_ID
    assert args[3] == REPO_ID
    assert args[4] == "abc1234"
    assert json.loads(args[5]) == body
    assert args[6] == "# Overview\n"
    assert json.loads(args[7]) == metadata


@pytest.mark.asyncio
async def test_record_page_version_passes_null_metadata_through() -> None:
    """``metadata=None`` should write SQL NULL, not the string ``"null"``."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    storage = _make_storage_with_conn(conn)

    await storage.record_page_version(
        page_id=PAGE_ID,
        generation_id=GEN_ID,
        repository_id=None,
        commit_sha=None,
        body={"blocks": []},
        body_markdown=None,
        metadata=None,
    )

    args = conn.execute.await_args.args
    assert args[3] is None  # repository_id
    assert args[4] is None  # commit_sha
    assert args[6] is None  # body_markdown
    assert args[7] is None  # metadata column receives NULL


@pytest.mark.asyncio
async def test_list_page_versions_returns_meta_dataclasses_newest_first() -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "generation_id": UUID("99999999-aaaa-bbbb-cccc-dddddddddddd"),
                "commit_sha": "abc1234abc1234",
                "created_at": dt.datetime(2026, 5, 5, 12, 0, tzinfo=dt.UTC),
            },
            {
                "generation_id": UUID("88888888-aaaa-bbbb-cccc-dddddddddddd"),
                "commit_sha": None,
                "created_at": dt.datetime(2026, 5, 4, 12, 0, tzinfo=dt.UTC),
            },
        ]
    )
    storage = _make_storage_with_conn(conn)

    versions = await storage.list_page_versions(PAGE_ID, limit=10)
    assert len(versions) == 2
    assert all(isinstance(v, PageVersionMeta) for v in versions)
    assert versions[0].commit_sha == "abc1234abc1234"
    assert versions[0].created_at == "2026-05-05T12:00:00+00:00"
    assert versions[1].commit_sha is None

    # SQL sanity: ORDER BY created_at DESC LIMIT $2 — defaults aren't allowed
    # to flip silently to ASC.
    args = conn.fetch.await_args.args
    sql = args[0]
    assert "ORDER BY created_at DESC" in sql
    assert args[1] == PAGE_ID
    assert args[2] == 10


@pytest.mark.asyncio
async def test_get_page_version_decodes_jsonb_strings() -> None:
    """asyncpg returns JSONB columns as ``str`` when the JSON codec
    isn't registered — the helper must json.loads them.
    """
    body = {"blocks": [{"type": "paragraph", "text": "hi"}], "title": "T"}
    metadata = {"tags": ["v1"]}
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "page_id": PAGE_ID,
            "generation_id": GEN_ID,
            "repository_id": REPO_ID,
            "commit_sha": "abc1234",
            "body": json.dumps(body),  # comes back as str
            "body_markdown": "# T\n",
            "metadata": json.dumps(metadata),  # comes back as str
            "created_at": dt.datetime(2026, 5, 5, 12, 0, tzinfo=dt.UTC),
        }
    )
    storage = _make_storage_with_conn(conn)

    result = await storage.get_page_version(PAGE_ID, GEN_ID)
    assert isinstance(result, PageVersionDetail)
    assert result.body == body
    assert result.metadata == metadata
    assert result.body_markdown == "# T\n"
    assert result.commit_sha == "abc1234"


@pytest.mark.asyncio
async def test_get_page_version_handles_dict_jsonb() -> None:
    """When asyncpg's JSON codec is registered, columns come back as dicts
    already — pass-through must not re-decode (json.loads on a dict raises).
    """
    body = {"blocks": []}
    metadata = {"tags": []}
    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "page_id": PAGE_ID,
            "generation_id": GEN_ID,
            "repository_id": None,
            "commit_sha": None,
            "body": body,  # dict, not str
            "body_markdown": None,
            "metadata": metadata,  # dict, not str
            "created_at": dt.datetime(2026, 5, 5, 12, 0, tzinfo=dt.UTC),
        }
    )
    storage = _make_storage_with_conn(conn)

    result = await storage.get_page_version(PAGE_ID, GEN_ID)
    assert result is not None
    assert result.body == body
    assert result.metadata == metadata


@pytest.mark.asyncio
async def test_get_page_version_returns_none_for_missing_row() -> None:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    storage = _make_storage_with_conn(conn)

    result = await storage.get_page_version(PAGE_ID, GEN_ID)
    assert result is None
