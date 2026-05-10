"""Unit tests for ``PostgresStorage`` page-link helpers (B13.2 / ТЗ АГТ-06).

Stubs the asyncpg connection so they run without a real Postgres. These
tests pin down:

  * ``record_page_links`` filters self-loops and non-positive weights.
  * The bulk INSERT uses ``ON CONFLICT DO UPDATE`` so re-running the
    finalize step on the same page accumulates weight rather than
    silently dropping rows.
  * ``list_page_links`` and ``list_inbound_links`` decode rows into the
    ``PageLink`` dataclass (sorted as the SQL says).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from source2doc.storage import PostgresStorage
from source2doc.storage.postgres import PageLink, PageLinkEntry


GEN_ID = UUID("11111111-2222-3333-4444-555555555555")


def _make_storage_with_conn(conn: MagicMock) -> PostgresStorage:
    pool = MagicMock()

    @asynccontextmanager
    async def acquire():
        yield conn

    pool.acquire = acquire
    storage = PostgresStorage(connection_string="postgres://stub")
    storage.pool = pool
    return storage


def _make_storage_with_transactional_conn(conn: MagicMock) -> PostgresStorage:
    """Storage whose connection supports ``async with conn.transaction()``."""

    @asynccontextmanager
    async def transaction():
        yield

    conn.transaction = transaction
    return _make_storage_with_conn(conn)


@pytest.mark.asyncio
async def test_record_page_links_drops_self_loops_and_zero_weight() -> None:
    conn = MagicMock()
    conn.executemany = AsyncMock()
    storage = _make_storage_with_transactional_conn(conn)

    edges = [
        PageLinkEntry(from_page_id="a", to_page_id="b", kind="symbol", weight=1),
        # self-loop — must be dropped
        PageLinkEntry(from_page_id="a", to_page_id="a", kind="symbol", weight=2),
        # zero weight — must be dropped
        PageLinkEntry(from_page_id="a", to_page_id="c", kind="symbol", weight=0),
        # negative weight — must be dropped
        PageLinkEntry(from_page_id="a", to_page_id="d", kind="symbol", weight=-1),
        # empty endpoint — must be dropped
        PageLinkEntry(from_page_id="", to_page_id="e", kind="symbol", weight=1),
    ]
    await storage.record_page_links(GEN_ID, edges)

    conn.executemany.assert_awaited_once()
    args = conn.executemany.await_args.args
    sql = args[0]
    assert "INSERT INTO page_links" in sql
    assert "ON CONFLICT" in sql
    assert "weight = page_links.weight + EXCLUDED.weight" in sql

    rows = args[1]
    assert rows == [(GEN_ID, "a", "b", "symbol", 1)]


@pytest.mark.asyncio
async def test_record_page_links_skips_db_when_no_valid_edges() -> None:
    """All-self-loops input must short-circuit before touching the pool."""
    conn = MagicMock()
    conn.executemany = AsyncMock()
    storage = _make_storage_with_transactional_conn(conn)

    await storage.record_page_links(
        GEN_ID,
        [
            PageLinkEntry(from_page_id="a", to_page_id="a", kind="symbol", weight=5),
            PageLinkEntry(from_page_id="b", to_page_id="b", kind="symbol", weight=2),
        ],
    )

    conn.executemany.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_page_links_passes_all_valid_rows() -> None:
    conn = MagicMock()
    conn.executemany = AsyncMock()
    storage = _make_storage_with_transactional_conn(conn)

    await storage.record_page_links(
        GEN_ID,
        [
            PageLinkEntry(from_page_id="a", to_page_id="b", kind="symbol", weight=2),
            PageLinkEntry(from_page_id="a", to_page_id="c", kind="symbol", weight=1),
            PageLinkEntry(from_page_id="b", to_page_id="c", kind="mention", weight=4),
        ],
    )

    rows = conn.executemany.await_args.args[1]
    assert rows == [
        (GEN_ID, "a", "b", "symbol", 2),
        (GEN_ID, "a", "c", "symbol", 1),
        (GEN_ID, "b", "c", "mention", 4),
    ]


@pytest.mark.asyncio
async def test_list_page_links_returns_pagelink_dataclasses() -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"from_page_id": "a", "to_page_id": "b", "kind": "symbol", "weight": 3},
            {"from_page_id": "a", "to_page_id": "c", "kind": "symbol", "weight": 1},
        ]
    )
    storage = _make_storage_with_conn(conn)

    edges = await storage.list_page_links(GEN_ID)
    assert all(isinstance(e, PageLink) for e in edges)
    assert edges[0].from_page_id == "a"
    assert edges[0].to_page_id == "b"
    assert edges[0].weight == 3

    sql = conn.fetch.await_args.args[0]
    assert "FROM page_links" in sql
    assert "WHERE generation_id = $1" in sql


@pytest.mark.asyncio
async def test_list_inbound_links_filters_by_target_and_orders_by_weight() -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"from_page_id": "overview", "to_page_id": "models", "kind": "symbol", "weight": 5},
            {"from_page_id": "guide", "to_page_id": "models", "kind": "symbol", "weight": 2},
        ]
    )
    storage = _make_storage_with_conn(conn)

    inbound = await storage.list_inbound_links(GEN_ID, "models")
    assert len(inbound) == 2
    assert inbound[0].from_page_id == "overview"

    args = conn.fetch.await_args.args
    sql = args[0]
    assert "WHERE generation_id = $1 AND to_page_id = $2" in sql
    assert "ORDER BY weight DESC" in sql
    assert args[1] == GEN_ID
    assert args[2] == "models"


@pytest.mark.asyncio
async def test_list_inbound_links_empty_when_no_rows() -> None:
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    storage = _make_storage_with_conn(conn)

    inbound = await storage.list_inbound_links(GEN_ID, "orphan")
    assert inbound == []
