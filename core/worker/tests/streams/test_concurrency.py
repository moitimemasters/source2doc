"""Asserts that ``run_consumer_loop`` honours the semaphore concurrency cap.

Verifies the B10 worker-concurrency integration: when a semaphore with N
permits is passed in, no more than N handlers are in flight at any time,
and a higher message count still completes (i.e. the loop *schedules*
beyond the cap, the semaphore just gates execution).
"""

from __future__ import annotations

import asyncio
import json

import fakeredis.aioredis
import pytest

from worker.streams.consumer import StreamMessage, run_consumer_loop


STREAM = "tasks:concurrency"
GROUP = "concurrency-group"
WORKER = "w-c"


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


async def test_run_consumer_loop_caps_in_flight_at_semaphore_value(redis) -> None:
    """With N=2 permits and 5 messages enqueued, in-flight count never exceeds 2."""

    semaphore = asyncio.Semaphore(2)
    in_flight = 0
    max_in_flight = 0
    completed: list[str] = []

    async def handler(msg: StreamMessage) -> None:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        # Hold the slot long enough that all messages overlap if the cap fails.
        await asyncio.sleep(0.05)
        completed.append(msg.message_id)
        in_flight -= 1

    # Enqueue 5 messages before starting the loop.
    for i in range(5):
        await redis.xadd(STREAM, {"type": "task.foo", "data": json.dumps({"i": i})})

    # The loop terminates as soon as ``running()`` returns False; we drive it
    # to False once we've accepted the expected number of completions.
    keep_running = True

    def running() -> bool:
        return keep_running

    async def watcher() -> None:
        nonlocal keep_running
        # Wait for all 5 to finish, then ask the loop to stop.
        while len(completed) < 5:
            await asyncio.sleep(0.01)
        keep_running = False

    await asyncio.gather(
        run_consumer_loop(
            redis,
            STREAM,
            GROUP,
            WORKER,
            handler,
            running,
            block_ms=50,
            max_retries=3,
            task_ttl=3600,
            semaphore=semaphore,
            concurrency=2,
        ),
        watcher(),
    )

    assert len(completed) == 5
    assert max_in_flight <= 2, f"expected <=2 concurrent handlers, observed {max_in_flight}"
    assert max_in_flight >= 2, "expected at least 2 concurrent handlers to prove parallelism"


async def test_run_consumer_loop_serial_when_no_semaphore(redis) -> None:
    """No semaphore -> strictly serial dispatch (max_in_flight == 1)."""

    in_flight = 0
    max_in_flight = 0
    completed: list[str] = []

    async def handler(msg: StreamMessage) -> None:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        completed.append(msg.message_id)
        in_flight -= 1

    for i in range(3):
        await redis.xadd(STREAM, {"type": "task.foo", "data": json.dumps({"i": i})})

    keep_running = True

    def running() -> bool:
        return keep_running

    async def watcher() -> None:
        nonlocal keep_running
        while len(completed) < 3:
            await asyncio.sleep(0.01)
        keep_running = False

    await asyncio.gather(
        run_consumer_loop(
            redis,
            STREAM,
            GROUP,
            WORKER,
            handler,
            running,
            block_ms=50,
            max_retries=3,
            task_ttl=3600,
            semaphore=None,
            concurrency=1,
        ),
        watcher(),
    )

    assert len(completed) == 3
    assert max_in_flight == 1
