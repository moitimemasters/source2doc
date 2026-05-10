"""Unit tests for ``PostgresStorage.record_agent_run`` (migration 20).

The runner-side persistence path leans on these guarantees:

  * the row INSERTs both ``messages`` and ``output`` as JSON-encoded text
    (asyncpg-compatible — Postgres casts via ``::jsonb``);
  * non-JSON-native values inside ``output`` (Decimal, UUID, dataclasses,
    Pydantic models) don't crash the call thanks to ``_json_default``;
  * the listing query filters by ``generation_id`` and orders newest-first.

Tests stub the asyncpg pool so they run without a real Postgres.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import dataclasses as dc
import datetime as dt
from decimal import Decimal
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from source2doc.storage import AgentRunRecord, PostgresStorage


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


@pytest.mark.asyncio
async def test_record_agent_run_inserts_basic_row() -> None:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 42})
    storage = _make_storage_with_conn(conn)

    started = dt.datetime(2026, 5, 6, 12, 0, 0, tzinfo=dt.UTC)
    finished = started + dt.timedelta(milliseconds=500)
    messages = [{"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hi"}]}]

    run_id = await storage.record_agent_run(
        generation_id=GEN_ID,
        agent_name="planner",
        messages=messages,
        attempt=1,
        started_at=started,
        finished_at=finished,
        duration_ms=500,
        success=True,
        request_count=2,
        input_tokens=120,
        output_tokens=80,
        cost_usd=0.0015,
        output={"plan": ["a", "b"]},
        trace_id="trace-1",
    )
    assert run_id == 42

    conn.fetchrow.assert_awaited_once()
    args = conn.fetchrow.await_args.args
    sql = args[0]
    assert "INSERT INTO agent_runs" in sql
    assert "RETURNING id" in sql

    # Positional args mirror the order in the INSERT VALUES list.
    (
        gen,
        page_id,
        section_id,
        agent_name,
        attempt,
        started_at,
        finished_at,
        duration_ms,
        success,
        error_type,
        error_message,
        request_count,
        input_tokens,
        output_tokens,
        total_tokens,
        cost,
        msgs_json,
        out_json,
        trace_id,
    ) = args[1:]
    assert gen == GEN_ID
    assert page_id is None
    assert section_id is None
    assert agent_name == "planner"
    assert attempt == 1
    assert started_at == started
    assert finished_at == finished
    assert duration_ms == 500
    assert success is True
    assert error_type is None
    assert error_message is None
    assert request_count == 2
    assert input_tokens == 120
    assert output_tokens == 80
    # total_tokens auto-derived when caller omits it
    assert total_tokens == 200
    assert cost == Decimal("0.0015")
    assert json.loads(msgs_json) == messages
    assert json.loads(out_json) == {"plan": ["a", "b"]}
    assert trace_id == "trace-1"


@pytest.mark.asyncio
async def test_record_agent_run_serialises_complex_output() -> None:
    """UUIDs, Decimals, datetimes and dataclasses inside ``output`` must
    survive ``json.dumps`` thanks to ``_json_default``."""

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 1})
    storage = _make_storage_with_conn(conn)

    @dc.dataclass
    class Section:
        page_id: str
        order: int

    payload = {
        "pages": [Section(page_id="a", order=1), Section(page_id="b", order=2)],
        "ts": dt.datetime(2026, 5, 6, 12, 0, 0, tzinfo=dt.UTC),
        "rid": UUID("22222222-3333-4444-5555-666666666666"),
        "rate": Decimal("0.05"),
    }

    await storage.record_agent_run(
        generation_id=GEN_ID,
        agent_name="subplanner",
        messages=[],
        page_id="root",
        section_id="overview",
        output=payload,
        success=True,
    )

    args = conn.fetchrow.await_args.args
    out_json = args[18]  # 19th positional after sql
    decoded = json.loads(out_json)
    # Dataclasses → dicts
    assert decoded["pages"][0] == {"page_id": "a", "order": 1}
    # datetime → isoformat
    assert decoded["ts"].startswith("2026-05-06T12:00:00")
    # UUID → str
    assert decoded["rid"] == "22222222-3333-4444-5555-666666666666"
    # Decimal → float
    assert decoded["rate"] == 0.05


@pytest.mark.asyncio
async def test_record_agent_run_records_failure() -> None:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 7})
    storage = _make_storage_with_conn(conn)

    run_id = await storage.record_agent_run(
        generation_id=GEN_ID,
        agent_name="critic",
        messages=[{"kind": "request"}],
        page_id="page-1",
        attempt=2,
        success=False,
        error_type="UnexpectedModelBehavior",
        error_message="model refused output schema",
    )
    assert run_id == 7

    args = conn.fetchrow.await_args.args
    success = args[9]
    error_type = args[10]
    error_message = args[11]
    out_json = args[18]
    assert success is False
    assert error_type == "UnexpectedModelBehavior"
    assert error_message == "model refused output schema"
    # output column must be NULL on failure (no run_result available)
    assert out_json is None


@pytest.mark.asyncio
async def test_list_agent_runs_decodes_json_strings() -> None:
    conn = MagicMock()
    started = dt.datetime(2026, 5, 6, 9, 0, 0, tzinfo=dt.UTC)
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": 2,
                "generation_id": GEN_ID,
                "page_id": "intro",
                "section_id": None,
                "agent_name": "writer",
                "attempt": 1,
                "started_at": started,
                "finished_at": started + dt.timedelta(seconds=2),
                "duration_ms": 2000,
                "success": True,
                "error_type": None,
                "error_message": None,
                "request_count": 3,
                "input_tokens": 500,
                "output_tokens": 300,
                "total_tokens": 800,
                "cost_usd": Decimal("0.02"),
                "messages": json.dumps([{"kind": "request"}]),
                "output": json.dumps({"title": "Intro"}),
                "trace_id": None,
            }
        ]
    )
    storage = _make_storage_with_conn(conn)

    rows = await storage.list_agent_runs(GEN_ID)
    assert len(rows) == 1
    record = rows[0]
    assert isinstance(record, AgentRunRecord)
    assert record.id == 2
    assert record.agent_name == "writer"
    assert record.messages == [{"kind": "request"}]
    assert record.output == {"title": "Intro"}
    assert record.cost_usd == Decimal("0.02")
    # Newest-first ORDER BY documented in SQL
    sql = conn.fetch.await_args.args[0]
    assert "ORDER BY started_at DESC" in sql


@pytest.mark.asyncio
async def test_get_agent_run_returns_none_for_missing() -> None:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    storage = _make_storage_with_conn(conn)

    record = await storage.get_agent_run(999)
    assert record is None
