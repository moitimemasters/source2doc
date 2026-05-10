import json
import uuid
from uuid import UUID, uuid4

import redis.asyncio as aioredis
import structlog

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import codetour as codetour_storage
from source2doc.storage.presets import ConfigPresetStorage

from app.errors import ResourceNotFoundError
from app.routes._shared.preset_resolver import resolve_configs
from app.routes.codetours.dto import (
    AdminCodetourFollowupRequest,
    AdminCodetourRequest,
    CodetourDetail,
    CodetourFollowupRequest,
    CodetourFollowupResponse,
    CodetourInfo,
    CodetourRequest,
    CodetourResponse,
)


CODETOUR_STREAM = "tasks:codetour"
CODETOUR_CONSUMER_GROUP = "codetour-workers"
CONFIG_TTL_SECONDS = 24 * 3600
TOUR_EVENTS_TTL_SECONDS = 24 * 3600


def _config_key(tour_id: UUID) -> str:
    return f"config:codetour:{tour_id}"


def _events_stream(tour_id: UUID) -> str:
    return f"events:codetour:{tour_id}"


def _set_logfire_trace_attribute(trace_id: str) -> None:
    """Best-effort tag the active logfire span with our trace_id."""
    try:
        import logfire

        logfire.current_span().set_attribute("trace_id", trace_id)
    except Exception:  # noqa: BLE001
        pass


async def create_codetour(
    request: CodetourRequest | AdminCodetourRequest,
    redis: aioredis.Redis,
    encryption: ConfigEncryption,
    storage: codetour_storage.CodetourStorage,
    presets: ConfigPresetStorage,
) -> CodetourResponse:
    tour_id = uuid4()
    trace_id = uuid.uuid4().hex
    config_key = _config_key(tour_id)

    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        generation_id=f"codetour:{tour_id}",
    )
    _set_logfire_trace_attribute(trace_id)

    try:
        is_admin = isinstance(request, AdminCodetourRequest)
        resolved = await resolve_configs(
            request_llm=request.llm if is_admin else None,
            request_embeddings=request.embeddings if is_admin else None,
            request_qdrant=request.qdrant if is_admin else None,
            preset_name=request.preset if is_admin else None,
            presets=presets,
            encryption=encryption,
        )

        user_config = {
            "llm": resolved["llm"],
            "embeddings": resolved.get("embeddings"),
            "qdrant": resolved.get("qdrant"),
        }
        encrypted = encryption.encrypt_config(user_config)
        await redis.setex(config_key, CONFIG_TTL_SECONDS, encrypted)

        await storage.create_pending_tour(
            tour_id=tour_id,
            generation_id=request.generation_id,
            request_payload={
                "query": request.query,
                "max_steps": request.max_steps,
                "mode": request.mode,
                "repo_id": str(request.repo_id) if request.repo_id else None,
            },
        )

        await _ensure_consumer_group(redis, CODETOUR_STREAM, CODETOUR_CONSUMER_GROUP)

        await redis.xadd(
            CODETOUR_STREAM,
            {
                "type": "codetour.requested",
                "data": json.dumps(
                    {
                        "kind": "initial",
                        "tour_id": str(tour_id),
                        "generation_id": str(request.generation_id),
                        "trace_id": trace_id,
                        "query": request.query,
                        "max_steps": request.max_steps,
                        "mode": request.mode,
                        "repo_id": str(request.repo_id) if request.repo_id else None,
                        "config_key": config_key,
                    }
                ),
            },
        )

        return CodetourResponse(
            tour_id=tour_id,
            generation_id=request.generation_id,
            trace_id=trace_id,
            status="pending",
            message="Code tour generation started",
        )
    finally:
        structlog.contextvars.clear_contextvars()


async def request_followup(
    tour_id: UUID,
    request: CodetourFollowupRequest | AdminCodetourFollowupRequest,
    redis: aioredis.Redis,
    encryption: ConfigEncryption,
    storage: codetour_storage.CodetourStorage,
    presets: ConfigPresetStorage,
) -> CodetourFollowupResponse:
    tour = await storage.get_codetour(tour_id)
    if not tour:
        raise ResourceNotFoundError(resource_type="codetour", resource_id=str(tour_id))
    if tour.get("status") != "completed":
        raise ValueError(
            f"Tour {tour_id} is not completed (status={tour.get('status')}); "
            "follow-ups are only allowed on completed tours."
        )
    if request.step_index >= len(tour.get("steps") or []):
        raise ValueError(
            f"step_index={request.step_index} is out of range for tour with "
            f"{len(tour.get('steps') or [])} steps"
        )

    request_id = uuid4()
    trace_id = uuid.uuid4().hex
    config_key = f"config:codetour-followup:{request_id}"

    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        generation_id=f"codetour:{tour_id}",
    )
    _set_logfire_trace_attribute(trace_id)

    try:
        is_admin = isinstance(request, AdminCodetourFollowupRequest)
        resolved = await resolve_configs(
            request_llm=request.llm if is_admin else None,
            request_embeddings=request.embeddings if is_admin else None,
            request_qdrant=request.qdrant if is_admin else None,
            preset_name=request.preset if is_admin else None,
            presets=presets,
            encryption=encryption,
        )

        user_config = {
            "llm": resolved["llm"],
            "embeddings": resolved.get("embeddings"),
            "qdrant": resolved.get("qdrant"),
        }
        encrypted = encryption.encrypt_config(user_config)
        await redis.setex(config_key, CONFIG_TTL_SECONDS, encrypted)

        await _ensure_consumer_group(redis, CODETOUR_STREAM, CODETOUR_CONSUMER_GROUP)

        await redis.xadd(
            CODETOUR_STREAM,
            {
                "type": "codetour.followup_requested",
                "data": json.dumps(
                    {
                        "kind": "followup",
                        "tour_id": str(tour_id),
                        "request_id": str(request_id),
                        "trace_id": trace_id,
                        "step_index": request.step_index,
                        "question": request.question,
                        "max_new_steps": request.max_new_steps,
                        "config_key": config_key,
                    }
                ),
            },
        )

        stream = _events_stream(tour_id)
        await redis.xadd(
            stream,
            {
                "type": "codetour.followup_requested",
                "data": json.dumps(
                    {
                        "tour_id": str(tour_id),
                        "request_id": str(request_id),
                        "trace_id": trace_id,
                        "step_index": request.step_index,
                        "question": request.question,
                    }
                ),
            },
        )
        await redis.expire(stream, TOUR_EVENTS_TTL_SECONDS)

        return CodetourFollowupResponse(
            tour_id=tour_id,
            request_id=request_id,
            trace_id=trace_id,
            status="pending",
            message="Follow-up generation started",
        )
    finally:
        structlog.contextvars.clear_contextvars()


async def cancel_codetour(
    tour_id: UUID,
    redis: aioredis.Redis,
    storage: codetour_storage.CodetourStorage,
) -> None:
    await storage.mark_cancelled(tour_id)
    await redis.delete(_config_key(tour_id))
    stream = _events_stream(tour_id)
    await redis.xadd(
        stream,
        {
            "type": "codetour.cancelled",
            "data": json.dumps({"tour_id": str(tour_id)}),
        },
    )
    await redis.expire(stream, TOUR_EVENTS_TTL_SECONDS)


async def stream_tour_events(redis: aioredis.Redis, tour_id: UUID):
    """Async generator yielding SSE-formatted lines for a tour's event stream."""

    stream = _events_stream(tour_id)
    last_id = "0"
    terminal = {"codetour.completed", "codetour.failed", "codetour.cancelled"}

    while True:
        result = await redis.xread({stream: last_id}, block=10_000, count=10)
        if not result:
            # Idle keep-alive frames are emitted by ``with_idle_pings`` at
            # the route layer; keep waiting for the next real event.
            continue
        for _, entries in result:
            for entry_id, fields in entries:
                last_id = entry_id
                event_type = fields.get("type", "message")
                data = fields.get("data", "{}")
                yield f"event: {event_type}\n"
                yield f"data: {data}\n\n"
                if event_type in terminal:
                    return


async def list_codetours_by_generation(
    generation_id: UUID,
    storage: codetour_storage.CodetourStorage,
) -> list[CodetourInfo]:
    tours_data = await storage.list_codetours_by_generation(generation_id)
    return [CodetourInfo(generation_id=str(generation_id), **tour) for tour in tours_data]


async def get_codetour(
    tour_id: UUID,
    storage: codetour_storage.CodetourStorage,
) -> CodetourDetail:
    tour_data = await storage.get_codetour(tour_id)
    if not tour_data:
        raise ResourceNotFoundError(resource_type="codetour", resource_id=str(tour_id))
    tour_data.pop("request_payload", None)
    return CodetourDetail(**tour_data)


async def list_all_codetours(
    storage: codetour_storage.CodetourStorage,
    limit: int,
    offset: int,
) -> list[CodetourInfo]:
    tours_data = await storage.list_all_codetours(limit=limit, offset=offset)
    return [CodetourInfo(**tour) for tour in tours_data]


async def _ensure_consumer_group(
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
