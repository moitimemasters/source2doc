"""Latency benchmark for status-query endpoints.

Closes ТЗ СКН-01: status queries must respond in <1s under modest
concurrent load. Fires N concurrent ``GET /api/v1/streams/{id}/events``
calls against the in-process app, measures wall-clock latency per call,
and asserts p50 < 200ms and p95 < 1000ms.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from httpx import AsyncClient
import pytest
from tests.perf._helpers import format_percentiles, percentiles


GENERATION_ID = "11111111-aaaa-bbbb-cccc-222222222222"
CONCURRENT_CALLS = 100
EVENTS_PER_STREAM = 20

# Budget per ТЗ СКН-01.
P50_BUDGET_S = 0.200
P95_BUDGET_S = 1.000


async def _seed_stream(redis: Any, stream_id: str, n_events: int) -> None:
    stream_key = f"events:{stream_id}"
    await redis.xadd(
        stream_key,
        {
            "type": "generation.requested",
            "data": json.dumps(
                {"name": "perf", "description": "latency benchmark", "repo_id": "abc"}
            ),
        },
    )
    for i in range(n_events - 1):
        await redis.xadd(
            stream_key,
            {
                "type": "step.started",
                "data": json.dumps({"step": f"step-{i}", "phase": "writer"}),
            },
        )


async def _timed_get(client: AsyncClient, url: str) -> float:
    start = time.perf_counter()
    response = await client.get(url)
    elapsed = time.perf_counter() - start
    assert response.status_code == 200, response.text
    return elapsed


@pytest.mark.perf
async def test_get_stream_events_latency_under_concurrency(
    client: AsyncClient, fake_redis: Any
) -> None:
    """p95 of GET /streams/{id}/events under ``CONCURRENT_CALLS`` parallel clients."""
    await _seed_stream(fake_redis, GENERATION_ID, EVENTS_PER_STREAM)

    url = f"/api/v1/streams/{GENERATION_ID}/events"

    # Warm-up: route registration and first-call import overhead would skew p50.
    for _ in range(3):
        warmup = await client.get(url)
        assert warmup.status_code == 200

    samples = await asyncio.gather(*(_timed_get(client, url) for _ in range(CONCURRENT_CALLS)))

    stats = percentiles(samples)
    print("\n" + format_percentiles(f"GET events x{CONCURRENT_CALLS}", stats))

    assert stats["p50"] < P50_BUDGET_S, (
        f"status p50 {stats['p50'] * 1000:.1f}ms exceeds budget {P50_BUDGET_S * 1000:.0f}ms"
    )
    assert stats["p95"] < P95_BUDGET_S, (
        f"status p95 {stats['p95'] * 1000:.1f}ms exceeds budget {P95_BUDGET_S * 1000:.0f}ms"
    )


@pytest.mark.perf
async def test_list_streams_latency_under_concurrency(client: AsyncClient, fake_redis: Any) -> None:
    """p95 of GET /streams listing across multiple seeded generations.

    Listing scans every stream key, so this exercises a slower path than
    the per-stream ``/events`` endpoint and is the most likely place to
    regress.
    """
    # Seed 10 streams so list has real work to do.
    for i in range(10):
        await _seed_stream(fake_redis, f"stream-{i:02d}", EVENTS_PER_STREAM)

    url = "/api/v1/streams"

    for _ in range(3):
        warmup = await client.get(url)
        assert warmup.status_code == 200

    samples = await asyncio.gather(*(_timed_get(client, url) for _ in range(CONCURRENT_CALLS)))

    stats = percentiles(samples)
    print("\n" + format_percentiles(f"GET streams x{CONCURRENT_CALLS}", stats))

    assert stats["p95"] < P95_BUDGET_S, (
        f"list-streams p95 {stats['p95'] * 1000:.1f}ms exceeds budget {P95_BUDGET_S * 1000:.0f}ms"
    )
