"""Gateway /api/v1/admin/trace/{trace_id} integration tests.

PMI-mapping: B13.4 / СПР-04 (Diagnostic endpoint for a trace_id).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from source2doc.storage import GenerationMetric

from app.security.admin import require_admin


TRACE_ID = "trace-abc-123"
GEN_ID_A = UUID("11111111-1111-1111-1111-111111111111")
GEN_ID_B = UUID("22222222-2222-2222-2222-222222222222")


def _make_metric(
    *,
    generation_id: UUID,
    step: str,
    prompt: int = 100,
    completion: int = 50,
    cost: float = 0.001,
    duration_ms: int = 500,
    model: str = "gpt-4",
) -> GenerationMetric:
    return GenerationMetric(
        id=1,
        generation_id=generation_id,
        trace_id=TRACE_ID,
        step=step,
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cost_usd=cost,
        duration_ms=duration_ms,
        step_started_at="2026-05-05T00:00:00+00:00",
        step_completed_at="2026-05-05T00:00:01+00:00",
        created_at="2026-05-05T00:00:00+00:00",
        extras={},
    )


async def test_trace_unknown_returns_empty_generations(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.find_generations_by_trace_id = AsyncMock(return_value=[])
    fake_storage.get_metrics_by_trace_id = AsyncMock(return_value=[])

    response = await client.get(f"/api/v1/admin/trace/{TRACE_ID}")
    assert response.status_code == 200

    body = response.json()
    assert body["trace_id"] == TRACE_ID
    assert body["generations"] == []
    assert "checked_at" in body and body["checked_at"]


async def test_trace_assembles_events_logs_metrics_for_one_generation(
    client: AsyncClient,
    fake_storage: MagicMock,
    fake_redis: Any,
) -> None:
    metrics = [
        _make_metric(generation_id=GEN_ID_A, step="planner"),
        _make_metric(generation_id=GEN_ID_A, step="writer", prompt=200, completion=100, cost=0.002),
    ]
    fake_storage.find_generations_by_trace_id = AsyncMock(return_value=[GEN_ID_A])
    fake_storage.get_metrics_by_trace_id = AsyncMock(return_value=metrics)

    # Seed events stream with one matching, one non-matching event.
    events_key = f"events:{GEN_ID_A}"
    await fake_redis.xadd(
        events_key,
        {
            "type": "step.started",
            "data": json.dumps({"step": "planner", "trace_id": TRACE_ID}),
        },
    )
    await fake_redis.xadd(
        events_key,
        {
            "type": "step.started",
            "data": json.dumps({"step": "planner", "trace_id": "other-trace"}),
        },
    )

    # Seed log stream with one matching entry (trace_id top-level).
    logs_key = f"logs:{GEN_ID_A}"
    await fake_redis.xadd(
        logs_key,
        {
            "level": "info",
            "event": "step started",
            "timestamp": "2026-05-05T00:00:00Z",
            "logger": "worker.docgen",
            "trace_id": TRACE_ID,
        },
    )
    await fake_redis.xadd(
        logs_key,
        {
            "level": "info",
            "event": "noise",
            "timestamp": "2026-05-05T00:00:00Z",
            "logger": "worker.docgen",
            "trace_id": "different",
        },
    )

    response = await client.get(f"/api/v1/admin/trace/{TRACE_ID}")
    assert response.status_code == 200

    body = response.json()
    assert body["trace_id"] == TRACE_ID
    assert len(body["generations"]) == 1

    gen = body["generations"][0]
    assert gen["generation_id"] == str(GEN_ID_A)

    assert len(gen["events"]) == 1
    assert gen["events"][0]["data"]["trace_id"] == TRACE_ID

    assert len(gen["logs"]) == 1
    assert gen["logs"][0]["event"] == "step started"

    assert len(gen["metrics"]) == 2
    assert {m["step"] for m in gen["metrics"]} == {"planner", "writer"}

    totals = gen["totals"]
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 150
    assert totals["cost_usd"] == 0.003
    assert totals["duration_s"] == 1.0  # 2 * 500 ms


async def test_trace_surfaces_multiple_generations(
    client: AsyncClient,
    fake_storage: MagicMock,
    fake_redis: Any,
) -> None:
    metrics = [
        _make_metric(generation_id=GEN_ID_A, step="planner"),
        _make_metric(generation_id=GEN_ID_B, step="writer"),
    ]
    fake_storage.find_generations_by_trace_id = AsyncMock(return_value=[GEN_ID_A, GEN_ID_B])
    fake_storage.get_metrics_by_trace_id = AsyncMock(return_value=metrics)

    response = await client.get(f"/api/v1/admin/trace/{TRACE_ID}")
    assert response.status_code == 200

    body = response.json()
    gen_ids = {g["generation_id"] for g in body["generations"]}
    assert gen_ids == {str(GEN_ID_A), str(GEN_ID_B)}


async def test_trace_requires_admin_when_override_removed(
    app_under_test: FastAPI,
) -> None:
    """Without an admin session cookie the endpoint must reject with 401."""
    # Drop the test-time auth bypass; the real require_admin dep will run.
    app_under_test.dependency_overrides.pop(require_admin, None)
    transport = ASGITransport(app=app_under_test, raise_app_exceptions=False)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as c,
        app_under_test.router.lifespan_context(app_under_test),
    ):
        response = await c.get(f"/api/v1/admin/trace/{TRACE_ID}")
    assert response.status_code == 401
