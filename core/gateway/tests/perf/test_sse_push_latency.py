"""Latency benchmark for SSE event delivery.

Closes ТЗ СКН-02: events pushed to a Redis stream must reach an
SSE-subscribed client in <1s. We invoke the gateway SSE generator
(``app.routes.streams.service._stream_events_generator``) directly,
iterate it as an async generator, and measure for each push the time
elapsed until the matching ``data: …`` frame is yielded.

Why we drive the generator directly instead of going through HTTP:
``httpx.AsyncClient`` over ``ASGITransport`` buffers the response body
and only flushes complete chunks once the underlying ASGI generator
ends — by design, since it's an in-process bridge with no real socket
to flush against. That hides per-event latency. Calling the generator
directly exercises the full SSE code path (Redis ``xread``, JSON
serialisation, SSE framing) without that buffering, which is what we
care about for СКН-02.

Sample sizes: ``N_STREAMS`` x ``EVENTS_PER_STREAM`` events. Sequential
to keep results comparable across runs.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from tests.perf._helpers import format_percentiles, percentiles

from app.config import Config
from app.routes.streams.service import _stream_events_generator


N_STREAMS = 10
EVENTS_PER_STREAM = 50
P95_BUDGET_S = 1.000


def _parse_sse_data(frame: str) -> dict | None:
    """Decode a single ``data: {...}\\n\\n`` SSE frame to JSON, or None."""
    line = frame.strip()
    if not line.startswith("data:"):
        return None
    payload = line[5:].lstrip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


async def _measure_one_stream(
    config: Config,
    redis: Any,
    stream_id: str,
    n_events: int,
) -> list[float]:
    """Subscribe to the SSE generator, push ``n_events``, return per-event latencies."""
    stream_key = f"events:{stream_id}"

    # Pre-create the stream so the generator skips its 1s "waiting" loop.
    await redis.xadd(
        stream_key,
        {
            "type": "generation.requested",
            "data": json.dumps({"name": stream_id, "description": "perf"}),
        },
    )

    push_times: dict[int, float] = {}
    latencies: list[float] = []
    consumed_seqs: set[int] = set()
    received = asyncio.Event()

    gen = _stream_events_generator(redis, config.redis, stream_id)

    async def consumer() -> None:
        async for frame in gen:
            payload = _parse_sse_data(frame)
            if payload is None:
                continue
            data = payload.get("data") or {}
            seq = data.get("seq")
            if seq is None:
                # Bootstrap, ping, or waiting frame — ignore.
                continue
            received_at = time.perf_counter()
            pushed_at = push_times.get(seq)
            if pushed_at is None:
                continue
            latencies.append(received_at - pushed_at)
            consumed_seqs.add(seq)
            if len(consumed_seqs) >= n_events:
                received.set()
                return

    consumer_task = asyncio.create_task(consumer())

    # Give the consumer a beat to subscribe before the first push.
    await asyncio.sleep(0.05)

    try:
        for seq in range(n_events):
            push_times[seq] = time.perf_counter()
            await redis.xadd(
                stream_key,
                {
                    "type": "step.completed",
                    "data": json.dumps({"seq": seq, "phase": "writer"}),
                },
            )
            # Yield to the loop so the consumer can read each event before
            # the next one is queued — measures delivery, not batching.
            await asyncio.sleep(0.005)

        await asyncio.wait_for(received.wait(), timeout=15.0)
    finally:
        consumer_task.cancel()
        try:
            await consumer_task
        except (asyncio.CancelledError, Exception):
            pass
        # Close the underlying async generator to release any pending xread.
        try:
            await gen.aclose()
        except Exception:
            pass

    return latencies


@pytest.mark.perf
async def test_sse_push_to_client_latency(fake_config: Config, fake_redis: Any) -> None:
    """p95 of push-to-SSE-frame latency across ``N_STREAMS`` x ``EVENTS_PER_STREAM``."""
    all_latencies: list[float] = []

    for i in range(N_STREAMS):
        stream_id = f"sse-perf-{i:02d}"
        latencies = await _measure_one_stream(fake_config, fake_redis, stream_id, EVENTS_PER_STREAM)
        assert len(latencies) == EVENTS_PER_STREAM, (
            f"stream {stream_id} delivered {len(latencies)} / {EVENTS_PER_STREAM} events"
        )
        all_latencies.extend(latencies)

    stats = percentiles(all_latencies)
    print(
        "\n"
        + format_percentiles(f"SSE push x{N_STREAMS} streams x{EVENTS_PER_STREAM} events", stats)
    )

    assert stats["p95"] < P95_BUDGET_S, (
        f"sse-push p95 {stats['p95'] * 1000:.1f}ms exceeds budget {P95_BUDGET_S * 1000:.0f}ms"
    )
