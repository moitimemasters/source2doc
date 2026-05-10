import json

import fakeredis.aioredis
import pytest

from worker.streams import task_state
from worker.streams.consumer import StreamMessage, dispatch_message


STREAM = "tasks:test"
GROUP = "test-group"
WORKER = "w-1"


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    yield r
    await r.aclose()


async def _add_and_read(redis) -> StreamMessage:
    await redis.xadd(STREAM, {"type": "task.foo", "data": json.dumps({"k": "v"})})
    msgs = await redis.xreadgroup(GROUP, WORKER, streams={STREAM: ">"}, count=1)
    msg_id, fields = msgs[0][1][0]
    return StreamMessage(
        message_id=msg_id,
        stream_name=STREAM,
        event_type=fields["type"],
        data=json.loads(fields["data"]),
    )


async def test_dispatch_calls_handler_acks_and_marks_done(redis):
    msg = await _add_and_read(redis)
    called = []

    async def handler(m):
        called.append(m)

    await dispatch_message(redis, STREAM, GROUP, msg, handler, WORKER, max_retries=3, task_ttl=3600)

    assert len(called) == 1
    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 0
    state = await task_state.get(redis, STREAM, msg.message_id)
    assert state.status == "done"
    assert state.attempts == 1


async def test_dispatch_skips_and_acks_done_message(redis):
    msg = await _add_and_read(redis)
    await task_state.mark_done(redis, STREAM, msg.message_id, 3600)
    called = []

    async def handler(m):
        called.append(m)

    await dispatch_message(redis, STREAM, GROUP, msg, handler, WORKER, max_retries=3, task_ttl=3600)

    assert len(called) == 0
    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 0  # ACKed


async def test_dispatch_skips_and_acks_dlq_message(redis):
    msg = await _add_and_read(redis)
    await task_state.mark_dlq(redis, STREAM, msg.message_id, 3600)
    called = []

    async def handler(m):
        called.append(m)

    await dispatch_message(redis, STREAM, GROUP, msg, handler, WORKER, max_retries=3, task_ttl=3600)

    assert len(called) == 0
    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 0  # ACKed


async def test_dispatch_moves_to_dlq_after_max_retries(redis):
    msg = await _add_and_read(redis)
    # Simulate 3 prior attempts
    for _ in range(3):
        await task_state.begin_processing(redis, STREAM, msg.message_id, "old-worker", 3600)

    called = []

    async def handler(m):
        called.append(m)

    await dispatch_message(redis, STREAM, GROUP, msg, handler, WORKER, max_retries=3, task_ttl=3600)

    assert len(called) == 0
    dlq_msgs = await redis.xrange(f"dlq:{STREAM}", "-", "+")
    assert len(dlq_msgs) == 1
    dlq_data = json.loads(dlq_msgs[0][1]["data"])
    assert dlq_data["original_stream"] == STREAM
    assert dlq_data["event_type"] == "task.foo"
    assert dlq_data["attempts"] == 3
    state = await task_state.get(redis, STREAM, msg.message_id)
    assert state.status == "dlq"
    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 0  # ACKed


async def test_dispatch_retries_processing_state_after_crash(redis):
    msg = await _add_and_read(redis)
    # Simulate crash: begin_processing ran but worker died before mark_done
    await task_state.begin_processing(redis, STREAM, msg.message_id, "crashed-worker", 3600)
    called = []

    async def handler(m):
        called.append(m)

    # Re-delivery after crash: status=processing must NOT be skipped
    await dispatch_message(redis, STREAM, GROUP, msg, handler, WORKER, max_retries=3, task_ttl=3600)

    assert len(called) == 1
    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 0
    state = await task_state.get(redis, STREAM, msg.message_id)
    assert state.status == "done"
    assert state.attempts == 2  # incremented by the retry


async def test_dispatch_does_not_ack_on_handler_exception(redis):
    msg = await _add_and_read(redis)

    async def failing_handler(m):
        raise ValueError("boom")

    await dispatch_message(
        redis, STREAM, GROUP, msg, failing_handler, WORKER, max_retries=3, task_ttl=3600
    )

    pending = await redis.xpending(STREAM, GROUP)
    assert pending["pending"] == 1  # still in PEL
    state = await task_state.get(redis, STREAM, msg.message_id)
    assert state.status == "processing"
    assert state.attempts == 1


async def test_dispatch_binds_trace_id_from_payload(redis):
    """B3.3 — when a task message carries trace_id, dispatch_message must
    bind it on structlog contextvars before invoking the handler so every
    log line emitted during processing inherits the correlation token."""

    import structlog

    trace_id = "deadbeef" * 4
    await redis.xadd(
        STREAM,
        {
            "type": "task.foo",
            "data": json.dumps({"k": "v", "trace_id": trace_id}),
        },
    )
    msgs = await redis.xreadgroup(GROUP, WORKER, streams={STREAM: ">"}, count=1)
    msg_id, fields = msgs[0][1][0]
    msg = StreamMessage(
        message_id=msg_id,
        stream_name=STREAM,
        event_type=fields["type"],
        data=json.loads(fields["data"]),
    )

    captured: dict = {}

    async def handler(_):
        # Read contextvars from inside the handler — that's where downstream
        # log calls would also pick them up.
        captured.update(structlog.contextvars.get_contextvars())

    await dispatch_message(
        redis, STREAM, GROUP, msg, handler, WORKER, max_retries=3, task_ttl=3600
    )

    assert captured.get("trace_id") == trace_id

    # And contextvars must be cleared on exit so the next message starts clean.
    assert structlog.contextvars.get_contextvars().get("trace_id") is None


async def test_dispatch_mints_trace_id_when_payload_missing(redis):
    """Legacy messages predate trace_id; the consumer must mint a fresh
    32-char hex token rather than leaving the chain unbound."""

    import structlog

    msg = await _add_and_read(redis)  # data has no trace_id field
    captured: dict = {}

    async def handler(_):
        captured.update(structlog.contextvars.get_contextvars())

    await dispatch_message(
        redis, STREAM, GROUP, msg, handler, WORKER, max_retries=3, task_ttl=3600
    )

    minted = captured.get("trace_id")
    assert isinstance(minted, str) and len(minted) == 32
    assert all(c in "0123456789abcdef" for c in minted)
