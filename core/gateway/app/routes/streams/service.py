import asyncio
from collections.abc import AsyncIterator
import json

from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from source2doc.config import RedisConfig
from source2doc.storage import PostgresStorage

from app.errors import RedisConnectionError, StreamNotFoundError
from app.routes._shared.sse import with_idle_pings
from app.routes.streams.dto import RepositoryInfoShort, StreamEvent, StreamInfo


def _iso_to_ts(iso_str: str | None) -> float:
    """Parse ISO-8601 to a unix timestamp; missing/invalid → 0."""
    if not iso_str:
        return 0.0
    try:
        import datetime as _dt

        return _dt.datetime.fromisoformat(iso_str).timestamp()
    except Exception:
        return 0.0


async def list_streams(
    redis: aioredis.Redis,
    config: RedisConfig,
    storage: PostgresStorage,
) -> list[StreamInfo]:
    """List streams by scanning Redis streams and deriving metadata from stream events.

    Legacy `generation_tasks` enrichment has been removed; the stream itself is the source of truth.
    """

    def _event_time_iso(message_id: str | None) -> str | None:
        if not message_id:
            return None
        try:
            ms = int(str(message_id).split("-", 1)[0])
            # Redis stream IDs are milliseconds since epoch.
            return (
                __import__("datetime")
                .datetime.fromtimestamp(ms / 1000, tz=__import__("datetime").timezone.utc)
                .isoformat()
            )
        except Exception:
            return None

    _COMPLETED_EVENT_TYPES = {"generation.completed", "codetour.completed"}
    _FAILED_EVENT_TYPES = {
        "step.failed",
        "task.failed",
        "generation.failed",
        "codetour.failed",
    }
    _STOPPED_EVENT_TYPES = {"task.stopped"}

    def _derive_status(recent_types: list[str], event_count: int) -> str | None:
        # Walk newest-first: the absolute latest event in the window wins.
        # Two concrete reasons for "newest beats any-in-window":
        #   1. ``generation.completed`` should win over a stale child
        #      ``task.failed`` (codetour fan-out can fail without
        #      affecting the primary docgen outcome).
        #   2. Resume re-emits a fresh ``*.completed`` transition on top
        #      of an existing ``task.failed`` — the new transition is
        #      newer, so status correctly flips from "failed" back to
        #      "running" without us having to delete the old failure
        #      marker from Redis.
        for t in recent_types:
            if t in _COMPLETED_EVENT_TYPES:
                return "completed"
            if t in _STOPPED_EVENT_TYPES:
                return "stopped"
            if t in _FAILED_EVENT_TYPES:
                return "failed"
            if t == "codetour.cancelled":
                return "cancelled"
            # Any other event (progress, mid-pipeline transition) on top of
            # the stream means work is in flight — short-circuit immediately
            # without scanning further back into history.
            return "running"
        return "pending"

    try:
        pattern = f"{config.stream_prefix}:*"
        keys: list[str] = []
        async for key in redis.scan_iter(match=pattern):
            keys.append(key)

        # Per-stream derived metadata
        derived: dict[str, dict] = {}
        repo_ids: set[str] = set()

        for key in keys:
            stream_id = key.split(":", 1)[1]
            event_count = await redis.xlen(key)

            recent_entries = await redis.xrevrange(key, count=50)
            last_event_id = recent_entries[0][0] if recent_entries else None

            recent_types = [fields.get("type", "unknown") for _, fields in recent_entries]
            status = _derive_status(recent_types, event_count)

            # Source-of-truth override: if the docgen state hash for this
            # generation has ``cancelled=true``, the run is stopped — full
            # stop. The events stream may still carry trailing emits from
            # in-flight handlers that completed AFTER /stop fired (those
            # emits are now suppressed in newer worker builds, but old
            # streams from before that fix still have them, and a slow
            # handler can race the cancel-flag check). The flag is the
            # authoritative signal — newest-event-wins is just a heuristic.
            if status not in ("completed",):
                state_key = f"state:docgen:{stream_id}"
                cancel_flag = await redis.hget(state_key, "cancelled")
                if cancel_flag == "true":
                    status = "stopped"

            # Find meta in the first few events (generation.requested contains name/description/repo_id)
            first_entries = await redis.xrange(key, count=10)
            requested_event_data: dict = {}
            started_at = None
            for message_id, fields in first_entries:
                if fields.get("type") == "generation.requested":
                    try:
                        requested_event_data = json.loads(fields.get("data", "{}"))
                    except Exception:
                        requested_event_data = {}
                    started_at = _event_time_iso(message_id)
                    break

            created_at = _event_time_iso(first_entries[0][0] if first_entries else None)

            completed_at = None
            if any(t in _COMPLETED_EVENT_TYPES for t in recent_types):
                for message_id, fields in recent_entries:
                    if fields.get("type") in _COMPLETED_EVENT_TYPES:
                        completed_at = _event_time_iso(message_id)
                        break

            repo_id = requested_event_data.get("repo_id")
            if isinstance(repo_id, str) and repo_id:
                repo_ids.add(repo_id)

            pipeline_id = "codetour" if stream_id.startswith("codetour:") else "docgen"

            derived[stream_id] = {
                "stream_id": stream_id,
                "pipeline_id": pipeline_id,
                "event_count": event_count,
                "last_event_id": last_event_id,
                "name": requested_event_data.get("name"),
                "description": requested_event_data.get("description"),
                "status": status,
                "repo_id": repo_id,
                "created_at": created_at,
                "started_at": started_at,
                "completed_at": completed_at,
            }

        # Fetch repositories (best effort). Prefer PostgresStorage API over direct pool usage.
        repo_map: dict[str, dict] = {}
        try:
            from uuid import UUID

            for rid in repo_ids:
                try:
                    repo = await storage.get_repository(UUID(rid))
                except Exception:
                    continue

                if not repo:
                    continue

                repo_map[str(repo.repo_id)] = {
                    "repo_id": str(repo.repo_id),
                    "name": repo.name,
                    "source_type": repo.source_type,
                    "git_url": repo.git_url,
                    "git_branch": repo.git_branch,
                }
        except Exception:
            pass

        streams: list[StreamInfo] = []
        for stream_id, meta in derived.items():
            repo_row = repo_map.get(meta.get("repo_id") or "")
            repository = None
            if repo_row:
                repository = RepositoryInfoShort(
                    name=repo_row["name"],
                    source_type=repo_row["source_type"],
                    git_url=repo_row.get("git_url"),
                    git_branch=repo_row.get("git_branch"),
                )

            streams.append(
                StreamInfo(
                    stream_id=stream_id,
                    pipeline_id=meta.get("pipeline_id", "docgen"),
                    event_count=meta["event_count"],
                    last_event_id=meta.get("last_event_id"),
                    name=meta.get("name"),
                    description=meta.get("description"),
                    status=meta.get("status"),
                    repo_id=meta.get("repo_id"),
                    repository=repository,
                    created_at=meta.get("created_at"),
                    started_at=meta.get("started_at"),
                    completed_at=meta.get("completed_at"),
                )
            )

        # Sort: active/running first, then newest first within each status.
        def sort_key(s: StreamInfo) -> tuple:
            status_order = {
                "running": 0,
                "pending": 1,
                "completed": 2,
                "stopped": 3,
                "failed": 4,
                "cancelled": 5,
                "timeout": 6,
            }
            order = status_order.get(s.status or "", 1)
            # Negative-prefixed string sort = newest first.
            return (order, -_iso_to_ts(s.created_at))

        streams.sort(key=sort_key)
        return streams
    except Exception as e:
        raise RedisConnectionError(error=str(e))


async def get_stream_events(
    redis: aioredis.Redis, config: RedisConfig, stream_id: str
) -> list[StreamEvent]:
    stream_name = f"{config.stream_prefix}:{stream_id}"

    try:
        exists = await redis.exists(stream_name)
        if not exists:
            raise StreamNotFoundError(stream_id=stream_id)

        messages = await redis.xrange(stream_name, "-", "+")

        events = []
        for message_id, fields in messages:
            data = json.loads(fields.get("data", "{}"))
            events.append(
                StreamEvent(
                    id=message_id,
                    type=fields.get("type", "unknown"),
                    data=data,
                    phase=data.get("phase"),
                    kind=data.get("kind"),
                    trace_id=data.get("trace_id"),
                )
            )

        return events
    except StreamNotFoundError:
        raise
    except Exception as e:
        raise RedisConnectionError(error=str(e))


async def _stream_events_generator(
    redis: aioredis.Redis, config: RedisConfig, stream_id: str
) -> AsyncIterator[str]:
    stream_name = f"{config.stream_prefix}:{stream_id}"

    try:
        wait_attempts = 0
        max_wait_attempts = 60

        while wait_attempts < max_wait_attempts:
            exists = await redis.exists(stream_name)
            if exists:
                break
            wait_attempts += 1
            yield f"data: {json.dumps({'type': 'waiting', 'message': 'Waiting for stream to be created...'})}\n\n"
            await _async_sleep(1.0)

        if wait_attempts >= max_wait_attempts:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Stream not found after timeout'})}\n\n"
            return

        last_id = "0"

        while True:
            messages = await redis.xread(
                {stream_name: last_id},
                count=10,
                block=5000,
            )

            if not messages:
                # Idle keep-alive frames are emitted by ``with_idle_pings``;
                # this loop just waits for the next real event.
                continue

            for _, stream_messages in messages:
                for message_id, fields in stream_messages:
                    data = json.loads(fields.get("data", "{}"))
                    event = StreamEvent(
                        id=message_id,
                        type=fields.get("type", "unknown"),
                        data=data,
                        phase=data.get("phase"),
                        kind=data.get("kind"),
                        trace_id=data.get("trace_id"),
                    )
                    yield f"data: {event.model_dump_json()}\n\n"
                    last_id = message_id

    except asyncio.CancelledError:
        # Client disconnected. Re-raise so Starlette can shut the response
        # down cleanly instead of swallowing the cancel and leaking the task.
        raise
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def stream_events(
    redis: aioredis.Redis, config: RedisConfig, stream_id: str
) -> StreamingResponse:
    return StreamingResponse(
        with_idle_pings(_stream_events_generator(redis, config, stream_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
