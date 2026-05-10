import json

from cryptography.fernet import Fernet
import fakeredis.aioredis
import pytest

from source2doc.config import PostgresConfig, QdrantConfig, RedisConfig, S3Config

from worker.config import GatewayWorkerConfig
from worker.encryption import ConfigEncryption
from worker.streams.consumer import StreamMessage


GENERATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def worker_config(encryption_key: str) -> GatewayWorkerConfig:
    return GatewayWorkerConfig(
        worker_id="test-worker",
        encryption_key=encryption_key,
        redis=RedisConfig(
            url="redis://localhost:6379",
            stream_prefix="custom_prefix",
            consumer_group="test-group",
            consumer_name="test-worker",
        ),
        postgres=PostgresConfig(),
        s3=S3Config(),
        qdrant=QdrantConfig(),
    )


@pytest.fixture
async def redis_with_config(worker_config: GatewayWorkerConfig):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)

    cipher = Fernet(worker_config.encryption_key.encode())
    user_config = {
        "repo_id": "test-repo-id",
        "name": "Test Generation",
        "description": "desc",
        "llm": {},
        "embeddings": {},
        "qdrant": {},
        "postgres": {},
        "generation": {},
    }
    encrypted = cipher.encrypt(json.dumps(user_config).encode()).decode()
    await r.set(f"config:{GENERATION_ID}", encrypted)

    yield r
    await r.aclose()


@pytest.mark.asyncio
async def test_process_task_message_uses_config_stream_prefix(
    redis_with_config, worker_config: GatewayWorkerConfig
):
    from worker.docgen.service.processor import process_task_message

    enc = ConfigEncryption(worker_config.encryption_key)

    msg = StreamMessage(
        message_id="1-0",
        stream_name="tasks:docgen",
        event_type="task.created",
        data={
            "generation_id": GENERATION_ID,
            "config_key": f"config:{GENERATION_ID}",
            "name": "Test Generation",
        },
    )

    await process_task_message(redis_with_config, enc, worker_config, msg)

    custom_stream = f"custom_prefix:{GENERATION_ID}"
    wrong_stream = f"events:{GENERATION_ID}"
    assert await redis_with_config.exists(custom_stream), (
        f"Expected stream at '{custom_stream}'"
    )
    assert not await redis_with_config.exists(wrong_stream), (
        f"Stream should NOT exist at hardcoded '{wrong_stream}'"
    )

    messages = await redis_with_config.xrange(custom_stream, "-", "+")
    assert len(messages) > 0
    event_type = messages[0][1].get("type")
    assert event_type == "generation.requested"


@pytest.mark.asyncio
async def test_process_task_message_propagates_trace_id_to_generation_requested(
    redis_with_config, worker_config: GatewayWorkerConfig
):
    """B3.3 — when the task message carries trace_id (bound on contextvars
    by ``dispatch_message``), the very first ``generation.requested`` event
    emitted into the per-generation stream must include it so subsequent
    handlers re-bind the same correlation token."""

    import structlog

    from worker.docgen.service.processor import process_task_message

    enc = ConfigEncryption(worker_config.encryption_key)

    msg = StreamMessage(
        message_id="1-0",
        stream_name="tasks:docgen",
        event_type="task.created",
        data={
            "generation_id": GENERATION_ID,
            "config_key": f"config:{GENERATION_ID}",
            "name": "Test Generation",
        },
    )

    trace_id = "abcd" * 8  # 32-char hex stand-in
    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    try:
        await process_task_message(redis_with_config, enc, worker_config, msg)
    finally:
        structlog.contextvars.clear_contextvars()

    custom_stream = f"custom_prefix:{GENERATION_ID}"
    messages = await redis_with_config.xrange(custom_stream, "-", "+")
    assert len(messages) > 0

    first_event_fields = messages[0][1]
    assert first_event_fields["type"] == "generation.requested"
    payload = json.loads(first_event_fields["data"])
    assert payload.get("trace_id") == trace_id, (
        f"Expected trace_id {trace_id!r} on first generation.requested event, "
        f"got payload={payload!r}"
    )


@pytest.mark.asyncio
async def test_cleanup_generation_uses_config_stream_prefix(worker_config):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    stream_key = f"{worker_config.redis.stream_prefix}:{GENERATION_ID}"
    wrong_stream_key = f"events:{GENERATION_ID}"

    # Add a stream entry and register it in the active streams set
    await r.xadd(stream_key, {"type": "generation.requested"})
    await r.sadd("active_event_streams", stream_key)

    from worker.docgen.service.processor import cleanup_generation
    await cleanup_generation(r, GENERATION_ID, worker_config.redis.stream_prefix)

    # The event stream itself stays around (its per-key TTL evicts it later)
    # so /streams keeps showing the run after completion. The active-set
    # membership is cleared so the "Active" count drops to 0.
    assert await r.exists(stream_key)
    assert not await r.exists(wrong_stream_key)
    assert not await r.sismember("active_event_streams", stream_key)

    await r.aclose()
