import dataclasses as dc
from datetime import UTC, datetime

import redis.asyncio as aioredis


@dc.dataclass
class TaskState:
    status: str  # "processing" | "done" | "dlq"
    worker_id: str
    attempts: int
    failure_emitted: bool = False


async def get(redis: aioredis.Redis, stream: str, msg_id: str) -> TaskState | None:
    key = f"task:{stream}:{msg_id}"
    data = await redis.hgetall(key)
    if not data:
        return None
    return TaskState(
        status=data.get("status", "processing"),
        worker_id=data.get("worker_id", ""),
        attempts=int(data.get("attempts", 0)),
        failure_emitted=data.get("failure_emitted", "0") == "1",
    )


async def mark_failure_emitted(
    redis: aioredis.Redis, stream: str, msg_id: str, ttl: int
) -> bool:
    """Set the per-message ``failure_emitted`` flag atomically.

    Returns True if this caller is the first to set it (so it should emit
    the ``task.failed`` event). Subsequent callers get False and must skip
    re-emitting — protects against double events on retry / DLQ paths.
    """
    key = f"task:{stream}:{msg_id}"
    # HSETNX returns 1 only when the field was newly created.
    created = await redis.hsetnx(key, "failure_emitted", "1")
    await redis.expire(key, ttl)
    return bool(created)


async def begin_processing(
    redis: aioredis.Redis, stream: str, msg_id: str, worker_id: str, ttl: int
) -> int:
    key = f"task:{stream}:{msg_id}"
    pipe = redis.pipeline()
    pipe.hincrby(key, "attempts", 1)
    pipe.hset(
        key,
        mapping={
            "status": "processing",
            "worker_id": worker_id,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    pipe.expire(key, ttl)
    results = await pipe.execute()
    return results[0]


async def mark_done(redis: aioredis.Redis, stream: str, msg_id: str, ttl: int) -> None:
    key = f"task:{stream}:{msg_id}"
    await redis.hset(
        key,
        mapping={
            "status": "done",
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    await redis.expire(key, ttl)


async def mark_dlq(redis: aioredis.Redis, stream: str, msg_id: str, ttl: int) -> None:
    key = f"task:{stream}:{msg_id}"
    await redis.hset(
        key,
        mapping={
            "status": "dlq",
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    await redis.expire(key, ttl)
