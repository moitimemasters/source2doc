"""Gateway agent-runs route integration tests (migration 20).

Verifies the route surface for inspecting per-generation Pydantic-AI runs:

  * ``GET /api/v1/generations/{id}/agent-runs`` lists rows newest-first
    and coerces ``Decimal`` cost to ``float``;
  * the detail endpoint returns the full ``messages`` + ``output`` JSON;
  * a missing detail row yields 404, an invalid UUID yields 422.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

from httpx import AsyncClient

from source2doc.storage import AgentRunRecord


GENERATION_ID = "11111111-2222-3333-4444-555555555555"


def _record(
    *,
    run_id: int,
    agent: str,
    page_id: str | None,
    section_id: str | None = None,
    success: bool = True,
    output: object | None = None,
    cost: Decimal | None = Decimal("0.0010"),
    started: dt.datetime | None = None,
) -> AgentRunRecord:
    started = started or dt.datetime(2026, 5, 6, 12, 0, 0, tzinfo=dt.UTC)
    return AgentRunRecord(
        id=run_id,
        generation_id=UUID(GENERATION_ID),
        page_id=page_id,
        section_id=section_id,
        agent_name=agent,
        attempt=1,
        started_at=started.isoformat(),
        finished_at=(started + dt.timedelta(seconds=1)).isoformat(),
        duration_ms=1000,
        success=success,
        error_type=None if success else "ValueError",
        error_message=None if success else "boom",
        request_count=2,
        input_tokens=120,
        output_tokens=80,
        total_tokens=200,
        cost_usd=cost,
        messages=[{"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hi"}]}],
        output=output,
        trace_id="trace-1",
    )


async def test_list_agent_runs_empty(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/generations/{GENERATION_ID}/agent-runs")
    assert response.status_code == 200
    body = response.json()
    assert body["generation_id"] == GENERATION_ID
    assert body["items"] == []
    assert body["limit"] == 200
    assert body["offset"] == 0


async def test_list_agent_runs_returns_rows(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.list_agent_runs.return_value = [
        _record(run_id=2, agent="writer", page_id="intro", output={"title": "Intro"}),
        _record(run_id=1, agent="planner", page_id=None, output={"plan": ["intro"]}),
    ]

    response = await client.get(
        f"/api/v1/generations/{GENERATION_ID}/agent-runs?limit=50&offset=10",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 50
    assert body["offset"] == 10
    assert len(body["items"]) == 2
    first = body["items"][0]
    assert first["id"] == 2
    assert first["agent_name"] == "writer"
    assert first["page_id"] == "intro"
    assert first["success"] is True
    assert first["input_tokens"] == 120
    assert first["output_tokens"] == 80
    assert first["total_tokens"] == 200
    assert first["cost_usd"] == 0.001
    # Detail-only fields must NOT leak into the summary payload.
    assert "messages" not in first
    assert "output" not in first

    fake_storage.list_agent_runs.assert_awaited_once()
    kwargs = fake_storage.list_agent_runs.await_args.kwargs
    assert kwargs == {"limit": 50, "offset": 10}
    assert fake_storage.list_agent_runs.await_args.args[0] == UUID(GENERATION_ID)


async def test_list_agent_runs_invalid_uuid_returns_422(client: AsyncClient) -> None:
    response = await client.get("/api/v1/generations/not-a-uuid/agent-runs")
    assert response.status_code == 422


async def test_get_agent_run_detail_returns_messages(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.get_agent_run.return_value = _record(
        run_id=42,
        agent="writer",
        page_id="intro",
        output={"title": "Intro", "blocks": []},
    )

    response = await client.get("/api/v1/generations/agent-runs/42")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 42
    assert body["agent_name"] == "writer"
    assert body["messages"] == [
        {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "hi"}]},
    ]
    assert body["output"] == {"title": "Intro", "blocks": []}
    assert fake_storage.get_agent_run.await_args.args == (42,)


async def test_get_agent_run_detail_returns_404_for_missing(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.get_agent_run.return_value = None

    response = await client.get("/api/v1/generations/agent-runs/9999")
    assert response.status_code == 404


async def test_list_agent_runs_records_failure_row(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """Failed runs must surface ``success=false`` plus error metadata."""
    fake_storage.list_agent_runs.return_value = [
        _record(
            run_id=3,
            agent="critic",
            page_id="intro",
            success=False,
            output=None,
            cost=None,
        ),
    ]

    response = await client.get(f"/api/v1/generations/{GENERATION_ID}/agent-runs")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["success"] is False
    assert item["error_type"] == "ValueError"
    assert item["error_message"] == "boom"
    assert item["cost_usd"] is None
