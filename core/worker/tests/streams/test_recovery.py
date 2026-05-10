"""Worker recovery & exactly-once integration tests.

PMI-mapping: 6.3.10 (Надёжность воркеров — exactly-once). These tests
exercise the multi-consumer scenarios that the manual PMI procedure
covers via `docker stop`/`docker start`:

  * Two consumers in the same group only see a message once each
    (Redis Streams XREADGROUP semantics).
  * A crashed consumer leaves the message in the Pending Entry List;
    a second consumer picks it up via XCLAIM after the idle timeout.
  * Re-delivery of a message that already reached `done` state is a no-op
    (idempotency guarantee).
  * After ``max_retries`` attempts the message is moved to the DLQ.
"""

import asyncio
import json

import fakeredis.aioredis
import pytest

from worker.streams import task_state
from worker.streams.consumer import (
    StreamMessage,
    claim_pending_messages,
    dispatch_message,
    ensure_consumer_group,
    read_stream_messages,
)


STREAM = "tasks:test"
GROUP = "test-group"


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await ensure_consumer_group(r, STREAM, GROUP)
    yield r
    await r.aclose()


async def _push(r, payload: dict | None = None) -> str:
    return await r.xadd(
        STREAM,
        {"type": "task.foo", "data": json.dumps(payload or {"k": "v"})},
    )


async def test_two_consumers_each_see_only_one_of_two_messages(redis) -> None:
    """Redis Streams consumer group: each XREADGROUP call delivers each
    message to exactly one consumer in the group. With two messages and
    two consumers, both consumers get exactly one each — no duplicates."""

    await _push(redis, {"n": 1})
    await _push(redis, {"n": 2})

    a = await read_stream_messages(redis, {STREAM: ">"}, GROUP, "worker-a", count=1, block_ms=10)
    b = await read_stream_messages(redis, {STREAM: ">"}, GROUP, "worker-b", count=1, block_ms=10)

    assert len(a) == 1
    assert len(b) == 1
    assert a[0].message_id != b[0].message_id


async def test_crashed_worker_message_claimed_by_second_worker(redis) -> None:
    """Worker A reads a message but crashes before ACK. After the idle
    timeout elapses, worker B's recovery pass picks the message up via
    XCLAIM and processes it."""

    msg_id = await _push(redis, {"task": "render"})

    a_msgs = await read_stream_messages(
        redis, {STREAM: ">"}, GROUP, "worker-a", count=1, block_ms=10
    )
    assert len(a_msgs) == 1
    assert a_msgs[0].message_id == msg_id

    # Simulate worker A crashing mid-task: state moves to "processing"
    # but ACK never happens.
    await task_state.begin_processing(redis, STREAM, msg_id, "worker-a", 3600)

    # PEL still holds the message for worker A.
    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 1

    # claim_pending_messages uses a strict `>` against the idle threshold,
    # so a freshly-delivered message with time_since_delivered=0 won't be
    # picked up if we pass 0. Sleep briefly so it accumulates idle time.
    await asyncio.sleep(0.05)

    claimed = await claim_pending_messages(
        redis, STREAM, GROUP, "worker-b", min_idle_time_ms=0
    )
    assert len(claimed) == 1
    assert claimed[0].message_id == msg_id

    handled = []

    async def handler(m: StreamMessage) -> None:
        handled.append(m)

    await dispatch_message(
        redis, STREAM, GROUP, claimed[0], handler, "worker-b", max_retries=3, task_ttl=3600
    )

    assert len(handled) == 1
    state = await task_state.get(redis, STREAM, msg_id)
    assert state is not None
    assert state.status == "done"
    # Attempt counter incremented from "processing" stub (1) to retry by B (2).
    assert state.attempts == 2

    # Message removed from PEL after B's ACK.
    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 0


async def test_idempotent_redelivery_after_done(redis) -> None:
    """If the same message is somehow re-delivered after being marked
    `done`, dispatch must NOT call the handler again — it just ACKs."""

    msg_id = await _push(redis)

    # First pass: complete the message.
    msgs = await read_stream_messages(redis, {STREAM: ">"}, GROUP, "w-1", count=1, block_ms=10)
    handled: list[StreamMessage] = []

    async def handler(m: StreamMessage) -> None:
        handled.append(m)

    await dispatch_message(
        redis, STREAM, GROUP, msgs[0], handler, "w-1", max_retries=3, task_ttl=3600
    )
    assert len(handled) == 1

    # Force a redelivery by manually re-XADDing the SAME message_id state
    # via a fresh dispatch — simulating XCLAIM after a network blip.
    fake_redelivery = StreamMessage(
        message_id=msg_id, stream_name=STREAM, event_type="task.foo", data={"k": "v"}
    )
    await dispatch_message(
        redis, STREAM, GROUP, fake_redelivery, handler, "w-2", max_retries=3, task_ttl=3600
    )

    assert len(handled) == 1, "Handler must not run twice on a done message"


async def test_dlq_after_max_retries_in_real_consumer_loop(redis) -> None:
    """Driver-style test: a flaky handler that always raises pushes the
    message to DLQ once the retry budget is exhausted."""

    msg_id = await _push(redis, {"flaky": True})

    async def always_fail(_m: StreamMessage) -> None:
        raise RuntimeError("transient")

    # Drive 3 dispatches simulating successive XCLAIM redeliveries.
    for attempt in range(3):
        msg = StreamMessage(
            message_id=msg_id, stream_name=STREAM, event_type="task.foo", data={"flaky": True}
        )
        await dispatch_message(
            redis, STREAM, GROUP, msg, always_fail, f"w-{attempt}",
            max_retries=3, task_ttl=3600,
        )

    # 4th delivery: attempts == max_retries → moved to DLQ.
    final = StreamMessage(
        message_id=msg_id, stream_name=STREAM, event_type="task.foo", data={"flaky": True}
    )
    await dispatch_message(
        redis, STREAM, GROUP, final, always_fail, "w-final",
        max_retries=3, task_ttl=3600,
    )

    state = await task_state.get(redis, STREAM, msg_id)
    assert state is not None
    assert state.status == "dlq"

    dlq_entries = await redis.xrange(f"dlq:{STREAM}", "-", "+")
    assert len(dlq_entries) == 1
    dlq_payload = json.loads(dlq_entries[0][1]["data"])
    assert dlq_payload["original_message_id"] == msg_id
    assert dlq_payload["attempts"] == 3


async def test_concurrent_dispatch_to_two_consumers_no_double_process(redis) -> None:
    """Two consumers each get a different message and dispatch concurrently.
    Neither handler must see the other consumer's message."""

    id_a = await _push(redis, {"n": "a"})
    id_b = await _push(redis, {"n": "b"})

    a_msgs = await read_stream_messages(redis, {STREAM: ">"}, GROUP, "w-a", count=1, block_ms=10)
    b_msgs = await read_stream_messages(redis, {STREAM: ">"}, GROUP, "w-b", count=1, block_ms=10)

    a_seen: list[str] = []
    b_seen: list[str] = []

    async def a_handler(m: StreamMessage) -> None:
        a_seen.append(m.data["n"])

    async def b_handler(m: StreamMessage) -> None:
        b_seen.append(m.data["n"])

    await asyncio.gather(
        dispatch_message(
            redis, STREAM, GROUP, a_msgs[0], a_handler, "w-a", max_retries=3, task_ttl=3600
        ),
        dispatch_message(
            redis, STREAM, GROUP, b_msgs[0], b_handler, "w-b", max_retries=3, task_ttl=3600
        ),
    )

    assert sorted(a_seen + b_seen) == ["a", "b"]
    assert len(a_seen) == 1 and len(b_seen) == 1

    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 0


async def test_xinfo_groups_tracks_consumers_independently(redis) -> None:
    """After two distinct consumers read from a group, XINFO CONSUMERS
    must list both — that's the basis for the heartbeat/timeout sweep."""

    await _push(redis, {"x": 1})
    await _push(redis, {"x": 2})

    await read_stream_messages(redis, {STREAM: ">"}, GROUP, "alpha", count=1, block_ms=10)
    await read_stream_messages(redis, {STREAM: ">"}, GROUP, "beta", count=1, block_ms=10)

    consumers = await redis.xinfo_consumers(STREAM, GROUP)
    names = sorted(c["name"] for c in consumers)
    assert names == ["alpha", "beta"]
    # Each holds exactly one pending entry.
    for c in consumers:
        assert c["pending"] == 1
