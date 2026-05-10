"""Gateway /api/v1/metrics/aggregate integration tests.

Closes ТЗ items МНТ-06, МТР-01, МТР-02 (B3.4) — verifies the aggregate
route returns bucketed token / cost / latency series for the dashboard.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from httpx import AsyncClient


async def test_aggregate_default_group_by_day(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """No query params -> ``group_by=day`` and storage rows surface verbatim."""
    fake_storage.get_metrics_buckets.return_value = [
        {
            "key": "2026-05-04",
            "tokens": 1000,
            "cost_usd": Decimal("0.12"),
            "duration_ms_p50": 1500,
            "duration_ms_p95": 4500,
            "runs": 10,
        },
        {
            "key": "2026-05-05",
            "tokens": 2500,
            "cost_usd": Decimal("0.30"),
            "duration_ms_p50": 1700,
            "duration_ms_p95": 5200,
            "runs": 25,
        },
    ]

    response = await client.get("/api/v1/metrics/aggregate")
    assert response.status_code == 200

    body = response.json()
    assert body["group_by"] == "day"
    assert len(body["buckets"]) == 2
    assert body["buckets"][0] == {
        "key": "2026-05-04",
        "tokens": 1000,
        "cost_usd": 0.12,
        "duration_ms_p50": 1500,
        "duration_ms_p95": 4500,
        "runs": 10,
    }
    assert body["buckets"][1]["tokens"] == 2500

    # Verify the storage layer was called with the expected canonicalised
    # group_by and a None date range (no query params supplied).
    fake_storage.get_metrics_buckets.assert_awaited_once()
    call_kwargs = fake_storage.get_metrics_buckets.await_args.kwargs
    assert call_kwargs["group_by"] == "day"
    assert call_kwargs["date_from"] is None
    assert call_kwargs["date_to"] is None


async def test_aggregate_group_by_model(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """``group_by=model`` returns buckets keyed by the model name."""
    fake_storage.get_metrics_buckets.return_value = [
        {
            "key": "gpt-4o",
            "tokens": 50_000,
            "cost_usd": Decimal("1.25"),
            "duration_ms_p50": 2300,
            "duration_ms_p95": 9000,
            "runs": 42,
        },
        {
            "key": "yandexgpt/latest",
            "tokens": 12_000,
            "cost_usd": None,  # No pricing entry — null sum is fine.
            "duration_ms_p50": 1100,
            "duration_ms_p95": 3500,
            "runs": 18,
        },
    ]

    response = await client.get("/api/v1/metrics/aggregate?group_by=model")
    assert response.status_code == 200

    body = response.json()
    assert body["group_by"] == "model"
    assert [b["key"] for b in body["buckets"]] == ["gpt-4o", "yandexgpt/latest"]
    assert body["buckets"][1]["cost_usd"] is None


async def test_aggregate_group_by_step(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """``group_by=step`` returns buckets keyed by handler name."""
    fake_storage.get_metrics_buckets.return_value = [
        {
            "key": "write",
            "tokens": 80_000,
            "cost_usd": Decimal("2.00"),
            "duration_ms_p50": 3200,
            "duration_ms_p95": 11_000,
            "runs": 60,
        },
        {
            "key": "review",
            "tokens": 30_000,
            "cost_usd": Decimal("0.75"),
            "duration_ms_p50": 1800,
            "duration_ms_p95": 6000,
            "runs": 60,
        },
        {
            "key": "plan",
            "tokens": 5000,
            "cost_usd": Decimal("0.10"),
            "duration_ms_p50": 900,
            "duration_ms_p95": 2100,
            "runs": 5,
        },
    ]

    response = await client.get("/api/v1/metrics/aggregate?group_by=step")
    assert response.status_code == 200

    body = response.json()
    assert body["group_by"] == "step"
    assert {b["key"] for b in body["buckets"]} == {"write", "review", "plan"}


async def test_aggregate_empty_range(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """Empty storage -> 200 with empty ``buckets`` list, not zeroed bars."""
    fake_storage.get_metrics_buckets.return_value = []

    response = await client.get(
        "/api/v1/metrics/aggregate?from=2024-01-01T00:00:00Z&to=2024-01-02T00:00:00Z&group_by=day"
    )
    assert response.status_code == 200

    body = response.json()
    assert body == {"group_by": "day", "buckets": []}


async def test_aggregate_invalid_group_by(client: AsyncClient) -> None:
    response = await client.get("/api/v1/metrics/aggregate?group_by=garbage")
    assert response.status_code == 422


async def test_aggregate_invalid_date(client: AsyncClient) -> None:
    response = await client.get("/api/v1/metrics/aggregate?from=not-a-date")
    assert response.status_code == 422


async def test_aggregate_inverted_range(client: AsyncClient) -> None:
    """``from`` > ``to`` is rejected before hitting storage."""
    response = await client.get("/api/v1/metrics/aggregate?from=2026-05-10&to=2026-05-01")
    assert response.status_code == 422
