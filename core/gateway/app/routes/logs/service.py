import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
import json

from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from app.routes._shared.sse import with_idle_pings
from app.routes.logs.dto import LogEntry, LogsResponse


LOG_STREAM_PREFIX = "logs"


def _parse_entry(message_id: str, fields: dict) -> LogEntry:
    return LogEntry(
        id=message_id,
        level=fields.get("level", "info"),
        event=fields.get("event", ""),
        timestamp=fields.get("timestamp", ""),
        logger=fields.get("logger", ""),
        extras=fields.get("extras"),
    )


def _iso_to_stream_id(iso_value: str | None, *, end: bool) -> str:
    """Translate an ISO 8601 timestamp into a Redis stream ID bound.

    Redis stream IDs are ``<ms-since-epoch>-<seq>``. We use ``<ms>-0`` for the
    inclusive lower bound and ``<ms>-*`` for the inclusive upper bound (the
    ``*`` matches any sequence within that millisecond). Returns Redis'
    sentinel bounds (``-`` / ``+``) when the value is missing or unparseable
    so callers degrade gracefully instead of returning empty results.
    """
    if not iso_value:
        return "-" if not end else "+"
    try:
        # ``fromisoformat`` accepts both naive and aware ISO strings; normalize
        # the trailing ``Z`` (UTC) to ``+00:00`` because Python <3.11 didn't.
        normalized = iso_value.replace("Z", "+00:00") if iso_value.endswith("Z") else iso_value
        dt = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return "-" if not end else "+"
    ms = int(dt.timestamp() * 1000)
    # Redis XRANGE accepts ``<ms>`` (no sequence suffix) as a partial ID:
    # for the ``start`` argument it's treated as ``<ms>-0`` and for ``end``
    # as ``<ms>-<MAX_SEQ>`` — which is exactly the inclusive bound we want.
    return f"{ms}" if end else f"{ms}-0"


async def get_logs(
    redis: aioredis.Redis,
    generation_id: str,
    *,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> LogsResponse:
    stream_key = f"{LOG_STREAM_PREFIX}:{generation_id}"
    start = _iso_to_stream_id(from_iso, end=False)
    end = _iso_to_stream_id(to_iso, end=True)
    try:
        messages = await redis.xrange(stream_key, start, end)
    except Exception:
        messages = []

    entries = [_parse_entry(mid, fields) for mid, fields in messages]
    return LogsResponse(generation_id=generation_id, entries=entries)


async def _stream_logs_generator(
    redis: aioredis.Redis,
    generation_id: str,
) -> AsyncIterator[str]:
    stream_key = f"{LOG_STREAM_PREFIX}:{generation_id}"
    last_id = "0"

    try:
        # First, replay all existing entries
        existing = await redis.xrange(stream_key, "-", "+")
        for message_id, fields in existing:
            entry = _parse_entry(message_id, fields)
            yield f"data: {entry.model_dump_json()}\n\n"
            last_id = message_id

        # Then tail for new entries
        while True:
            messages = await redis.xread(
                {stream_key: last_id},
                count=50,
                block=5000,
            )

            if not messages:
                # Idle keep-alive frames are emitted by ``with_idle_pings``;
                # just wait for the next real entry.
                continue

            for _, stream_messages in messages:
                for message_id, fields in stream_messages:
                    entry = _parse_entry(message_id, fields)
                    yield f"data: {entry.model_dump_json()}\n\n"
                    last_id = message_id

    except asyncio.CancelledError:
        # Propagate so Starlette can release the connection without leaving
        # this generator pinned in the event loop.
        raise
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


async def stream_logs(
    redis: aioredis.Redis,
    generation_id: str,
) -> StreamingResponse:
    return StreamingResponse(
        with_idle_pings(_stream_logs_generator(redis, generation_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
