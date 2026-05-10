"""Gateway /api/v1/generations/{id}/metrics integration tests.

Closes ТЗ items LLM-03, LLM-04, МТР-03 (B3.1) — verifies the route
returns aggregated token usage and per-step breakdown from the storage
layer.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from httpx import AsyncClient

from source2doc.storage import GenerationMetric


GENERATION_ID = "11111111-2222-3333-4444-555555555555"


async def test_metrics_returns_zero_aggregate_when_no_rows(client: AsyncClient) -> None:
    """No metric rows recorded => 200 with all-zero totals and empty steps.

    The wiki UI relies on this contract to silently hide the badge instead
    of erroring out for older bundles that pre-date B3.1.
    """
    response = await client.get(f"/api/v1/generations/{GENERATION_ID}/metrics")
    assert response.status_code == 200

    body = response.json()
    assert body["generation_id"] == GENERATION_ID
    assert body["totals"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": None,
    }
    assert body["steps"] == []


async def test_metrics_returns_aggregate_and_steps(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """Storage rows are surfaced verbatim with Decimal -> float coercion."""
    from uuid import UUID

    fake_storage.get_metrics_for_generation.return_value = [
        GenerationMetric(
            id=1,
            generation_id=UUID(GENERATION_ID),
            step="plan",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=Decimal("0.001"),
            created_at="2026-05-05T00:00:00+00:00",
        ),
        GenerationMetric(
            id=2,
            generation_id=UUID(GENERATION_ID),
            step="write",
            model="gpt-4o",
            prompt_tokens=300,
            completion_tokens=200,
            total_tokens=500,
            cost_usd=Decimal("0.005"),
            created_at="2026-05-05T00:00:01+00:00",
        ),
    ]
    fake_storage.get_metrics_aggregate.return_value = {
        "prompt_tokens": 400,
        "completion_tokens": 250,
        "total_tokens": 650,
        "cost_usd": Decimal("0.006"),
    }

    response = await client.get(f"/api/v1/generations/{GENERATION_ID}/metrics")
    assert response.status_code == 200

    body = response.json()
    assert body["totals"] == {
        "prompt_tokens": 400,
        "completion_tokens": 250,
        "total_tokens": 650,
        "cost_usd": 0.006,
    }
    assert len(body["steps"]) == 2
    assert body["steps"][0]["step"] == "plan"
    assert body["steps"][0]["cost_usd"] == 0.001
    assert body["steps"][1]["step"] == "write"
    assert body["steps"][1]["total_tokens"] == 500


async def test_metrics_invalid_uuid_returns_422(client: AsyncClient) -> None:
    response = await client.get("/api/v1/generations/not-a-uuid/metrics")
    assert response.status_code == 422
