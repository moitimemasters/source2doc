import asyncio
import collections.abc as cabc
import dataclasses as dc
import json
import typing as tp
import uuid

import redis.asyncio as aioredis
import structlog

from source2doc.logging import get_logger
from source2doc.resilience.external import redis_retry

from worker.streams import task_state as task_state_mod


logger = get_logger(__name__)


def trace_id_from_context() -> str | None:
    """Read the current ``trace_id`` from structlog contextvars.

    Returns ``None`` when no trace is bound — callers should mint a fresh
    one before the first log line, or accept the missing tag.
    """
    ctx = structlog.contextvars.get_contextvars()
    value = ctx.get("trace_id")
    return value if isinstance(value, str) else None


def _set_logfire_trace_attribute(trace_id: str) -> None:
    """Best-effort tag the active logfire span with our trace_id."""
    try:
        import logfire

        logfire.current_span().set_attribute("trace_id", trace_id)
    except Exception:  # noqa: BLE001
        pass


@dc.dataclass
class StreamMessage:
    message_id: str
    stream_name: str
    event_type: str
    data: dict[str, tp.Any]


type MessageHandler = cabc.Callable[[StreamMessage], cabc.Coroutine[tp.Any, tp.Any, None]]


async def ensure_consumer_group(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
) -> None:
    try:
        await redis.xgroup_create(
            name=stream_name,
            groupname=group_name,
            id="0",
            mkstream=True,
        )
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def read_stream_messages(
    redis: aioredis.Redis,
    streams: dict[str, str],
    group_name: str,
    consumer_name: str,
    count: int = 10,
    block_ms: int = 5000,
) -> list[StreamMessage]:
    messages = await redis.xreadgroup(
        groupname=group_name,
        consumername=consumer_name,
        streams=streams,
        count=count,
        block=block_ms,
    )

    if not messages:
        return []

    result = []
    for stream_name, stream_messages in messages:
        for message_id, fields in stream_messages:
            event_type = fields.get("type", "unknown")
            data = json.loads(fields.get("data", "{}"))
            result.append(
                StreamMessage(
                    message_id=message_id,
                    stream_name=stream_name,
                    event_type=event_type,
                    data=data,
                )
            )

    return result


@redis_retry()
async def ack_message(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
    message_id: str,
) -> None:
    await redis.xack(stream_name, group_name, message_id)


async def claim_pending_messages(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
    consumer_name: str,
    min_idle_time_ms: int,
    count: int = 100,
) -> list[StreamMessage]:
    pending = await redis.xpending_range(
        name=stream_name,
        groupname=group_name,
        min="-",
        max="+",
        count=count,
    )

    result = []
    for msg in pending:
        if msg["time_since_delivered"] > min_idle_time_ms:
            claimed = await redis.xclaim(
                name=stream_name,
                groupname=group_name,
                consumername=consumer_name,
                min_idle_time=min_idle_time_ms,
                message_ids=[msg["message_id"]],
            )

            for message_id, fields in claimed:
                event_type = fields.get("type", "unknown")
                data = json.loads(fields.get("data", "{}"))
                result.append(
                    StreamMessage(
                        message_id=message_id,
                        stream_name=stream_name,
                        event_type=event_type,
                        data=data,
                    )
                )

    return result


@redis_retry()
async def _xadd_event(
    redis: aioredis.Redis,
    stream_name: str,
    event_type: str,
    payload: str,
) -> str:
    return await redis.xadd(
        name=stream_name,
        fields={
            "type": event_type,
            "data": payload,
        },
    )


async def emit_to_stream(
    redis: aioredis.Redis,
    stream_name: str,
    event_type: str,
    data: dict[str, tp.Any],
    ttl_seconds: int = 86400,
) -> str:
    message_id = await _xadd_event(redis, stream_name, event_type, json.dumps(data))
    await redis.expire(stream_name, ttl_seconds)
    logger.info("event_emitted", stream=stream_name, event_type=event_type)
    return message_id


async def discover_streams(
    redis: aioredis.Redis,
    pattern: str,
) -> list[str]:
    cursor = 0
    streams = []

    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
        streams.extend(keys)
        if cursor == 0:
            break

    return streams


@redis_retry()
async def _xadd_dlq(
    redis: aioredis.Redis,
    dlq_stream: str,
    payload: str,
) -> None:
    await redis.xadd(
        dlq_stream,
        {
            "type": "task.failed",
            "data": payload,
        },
    )


async def _move_to_dlq(
    redis: aioredis.Redis,
    stream_name: str,
    msg: StreamMessage,
    attempts: int,
    task_ttl: int,
) -> None:
    dlq_stream = f"dlq:{stream_name}"
    payload = json.dumps(
        {
            "original_message_id": msg.message_id,
            "original_stream": stream_name,
            "event_type": msg.event_type,
            "data": msg.data,
            "attempts": attempts,
        }
    )
    await _xadd_dlq(redis, dlq_stream, payload)
    await redis.expire(dlq_stream, task_ttl)
    logger.warning(
        "message_moved_to_dlq",
        stream=stream_name,
        message_id=msg.message_id,
        attempts=attempts,
    )


async def dispatch_message(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
    msg: StreamMessage,
    handler: MessageHandler,
    worker_id: str,
    max_retries: int = 3,
    task_ttl: int = 86400,
) -> None:
    state = await task_state_mod.get(redis, stream_name, msg.message_id)

    if state and state.status in ("done", "dlq"):
        await ack_message(redis, stream_name, group_name, msg.message_id)
        logger.info(
            "message_already_processed",
            message_id=msg.message_id,
            status=state.status,
            stream=stream_name,
        )
        return

    attempts = state.attempts if state else 0
    if attempts >= max_retries:
        await _emit_task_failure_event_once(
            redis, msg, stream_name, attempts, "max_retries_exceeded", task_ttl,
        )
        await _move_to_dlq(redis, stream_name, msg, attempts, task_ttl)
        await task_state_mod.mark_dlq(redis, stream_name, msg.message_id, task_ttl)
        await ack_message(redis, stream_name, group_name, msg.message_id)
        return

    await task_state_mod.begin_processing(redis, stream_name, msg.message_id, worker_id, task_ttl)

    # Pull trace_id off the in-flight payload so every log line and any
    # downstream events carry the same correlation token. Mint a fresh one
    # for legacy messages so the chain never silently breaks.
    trace_id = msg.data.get("trace_id") if isinstance(msg.data, dict) else None
    if not isinstance(trace_id, str) or not trace_id:
        trace_id = uuid.uuid4().hex
        logger.warning(
            "stream_message_missing_trace_id",
            stream=stream_name,
            message_id=msg.message_id,
            event_type=msg.event_type,
            minted_trace_id=trace_id,
        )

    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    _set_logfire_trace_attribute(trace_id)

    try:
        try:
            await handler(msg)
            await task_state_mod.mark_done(redis, stream_name, msg.message_id, task_ttl)
            await ack_message(redis, stream_name, group_name, msg.message_id)
        except Exception as e:
            current_attempt = attempts + 1
            logger.exception(
                "message_handler_error",
                stream=stream_name,
                message_id=msg.message_id,
                error=str(e),
                attempt=current_attempt,
                max_retries=max_retries,
            )
            if current_attempt >= max_retries:
                # Final attempt exhausted — surface failure + DLQ + ack so
                # the PEL stops holding this message.
                await _emit_task_failure_event_once(
                    redis, msg, stream_name, current_attempt,
                    str(e) or type(e).__name__, task_ttl,
                )
                await _move_to_dlq(redis, stream_name, msg, current_attempt, task_ttl)
                await task_state_mod.mark_dlq(
                    redis, stream_name, msg.message_id, task_ttl
                )
                await ack_message(redis, stream_name, group_name, msg.message_id)
            else:
                # NACK semantics: leave the message in PEL. The periodic
                # XCLAIM sweep in run_consumer_loop will redeliver it after
                # min_idle_time_ms so a transient handler failure (network
                # blip, embedder hiccup) doesn't kill the whole task.
                logger.warning(
                    "message_handler_will_retry",
                    stream=stream_name,
                    message_id=msg.message_id,
                    attempt=current_attempt,
                    max_retries=max_retries,
                )
    finally:
        structlog.contextvars.clear_contextvars()


async def _emit_task_failure_event_once(
    redis: aioredis.Redis,
    msg: StreamMessage,
    stream_name: str,
    attempts: int,
    error: str,
    task_ttl: int,
) -> None:
    """Emit ``task.failed`` exactly once per source message.

    The same delivery can hit this path twice (handler exception then
    redelivery → max_retries branch). Without dedup the UI sees two
    ``task.failed`` events. We use a SETNX-style flag in task_state to
    guarantee only the first caller emits.
    """
    generation_id = msg.data.get("generation_id")
    if not generation_id:
        return

    is_first = await task_state_mod.mark_failure_emitted(
        redis, stream_name, msg.message_id, task_ttl
    )
    if not is_first:
        logger.info(
            "task_failure_already_emitted",
            stream=stream_name,
            message_id=msg.message_id,
        )
        return

    event_stream = f"events:{generation_id}"
    try:
        await emit_to_stream(
            redis,
            event_stream,
            "task.failed",
            {
                "generation_id": generation_id,
                "task_stream": stream_name,
                "event_type": msg.event_type,
                "attempts": attempts,
                "error": error,
            },
            task_ttl,
        )
    except Exception as emit_err:
        logger.error(
            "task_failure_emit_failed",
            stream=event_stream,
            error=str(emit_err),
        )

    log_stream = f"logs:{generation_id}"
    try:
        await _xadd_failure_log(
            redis,
            log_stream,
            stream_name,
            msg.event_type,
            attempts,
            error,
        )
        await redis.expire(log_stream, task_ttl)
    except Exception as log_err:
        logger.error(
            "task_failure_log_failed",
            stream=log_stream,
            error=str(log_err),
        )


@redis_retry()
async def _xadd_failure_log(
    redis: aioredis.Redis,
    log_stream: str,
    task_stream: str,
    event_type: str,
    attempts: int,
    error: str,
) -> None:
    await redis.xadd(
        log_stream,
        {
            "level": "error",
            "event": "task_handler_failed",
            "timestamp": "",
            "logger": "worker.streams.consumer",
            "extras": json.dumps(
                {
                    "task_stream": task_stream,
                    "event_type": event_type,
                    "attempts": attempts,
                    "error": error,
                },
                default=str,
            ),
        },
        maxlen=10_000,
        approximate=True,
    )


async def run_consumer_loop(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
    consumer_name: str,
    handler: MessageHandler,
    running: cabc.Callable[[], bool],
    block_ms: int = 5000,
    min_idle_time_ms: int = 120000,
    max_retries: int = 3,
    task_ttl: int = 86400,
    semaphore: asyncio.Semaphore | None = None,
    concurrency: int = 1,
) -> None:
    """Read messages from ``stream_name`` and dispatch them through ``handler``.

    When ``semaphore`` is provided, in-flight dispatches run as concurrent
    tasks gated by the semaphore (cap = semaphore initial value). Without a
    semaphore, dispatches run serially — preserving the original behaviour
    used by tests and any single-flight worker.
    """
    await ensure_consumer_group(redis, stream_name, group_name)

    in_flight: set[asyncio.Task] = set()

    async def dispatch(msg: StreamMessage) -> None:
        await dispatch_message(
            redis, stream_name, group_name, msg, handler, consumer_name, max_retries, task_ttl
        )

    async def gated_dispatch(msg: StreamMessage) -> None:
        assert semaphore is not None
        async with semaphore:
            await dispatch(msg)

    def schedule(msg: StreamMessage) -> asyncio.Task:
        coro = gated_dispatch(msg) if semaphore is not None else dispatch(msg)
        task = asyncio.create_task(coro)
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
        return task

    # Startup PEL sweep — pick up anything left over from a previous
    # process (crash, OOM, abrupt restart) before reading new messages.
    pending = await claim_pending_messages(
        redis, stream_name, group_name, consumer_name, min_idle_time_ms
    )
    for msg in pending:
        if semaphore is None:
            await dispatch(msg)
        else:
            schedule(msg)

    # Read up to ``count`` messages per poll. With no semaphore we still poll
    # one at a time so the existing serial-dispatch tests stay deterministic.
    poll_count = 1 if semaphore is None else max(1, concurrency)

    # Periodic PEL recovery — re-claim our own stale messages so that a
    # transient handler failure (network blip, embedder hiccup) gets a
    # second/third chance via dispatch_message's max_retries gate. Without
    # this, a single-worker deployment has zero auto-recovery: NACK'd
    # messages would sit in PEL forever.
    pel_sweep_every_polls = max(1, 30_000 // max(1, block_ms))
    polls_since_sweep = 0

    while running():
        try:
            messages = await read_stream_messages(
                redis,
                {stream_name: ">"},
                group_name,
                consumer_name,
                count=poll_count,
                block_ms=block_ms,
            )

            for msg in messages:
                if semaphore is None:
                    await dispatch(msg)
                else:
                    schedule(msg)

            polls_since_sweep += 1
            if polls_since_sweep >= pel_sweep_every_polls:
                polls_since_sweep = 0
                reclaimed = await claim_pending_messages(
                    redis,
                    stream_name,
                    group_name,
                    consumer_name,
                    min_idle_time_ms,
                )
                if reclaimed:
                    logger.info(
                        "pel_recovery_reclaimed",
                        stream=stream_name,
                        count=len(reclaimed),
                    )
                    for msg in reclaimed:
                        if semaphore is None:
                            await dispatch(msg)
                        else:
                            schedule(msg)

        except asyncio.CancelledError:
            break
        except aioredis.ResponseError as e:
            if "NOGROUP" in str(e):
                logger.warning(
                    "consumer_group_missing_recreating",
                    stream=stream_name,
                    group=group_name,
                )
                await ensure_consumer_group(redis, stream_name, group_name)
                continue
            logger.exception("consumer_loop_error", stream=stream_name, error=str(e))
            await asyncio.sleep(1)
        except Exception as e:
            logger.exception("consumer_loop_error", stream=stream_name, error=str(e))
            await asyncio.sleep(1)

    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)
