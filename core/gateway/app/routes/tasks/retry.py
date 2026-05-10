"""Retry-failed-generation endpoint.

A failed docgen task can land in one of two reachable states from the
gateway's perspective:

1. The worker exhausted ``max_retries`` and pushed the original message
   to ``dlq:{tasks_stream}`` (see ``worker.streams.consumer._move_to_dlq``).
   The DLQ entry preserves the *original* stream payload — including the
   ``config_key`` that points at the encrypted config blob.
2. The handler raised mid-processing and emitted a ``task.failed`` event
   on ``events:{generation_id}`` but the message hasn't been DLQ'd yet
   (still in pending, will be redelivered on the next claim, etc.). In
   that window we can reconstruct the original payload by reading
   ``task_stream`` off the ``task.failed`` event and scanning the source
   stream — but the simpler path here is to read the encrypted blob
   directly from ``config:{old_generation_id}`` and re-enqueue.

The endpoint mints a *new* ``generation_id`` (UUIDs are assumed unique
downstream — bundles, qdrant collections, event streams all key off it,
so reusing the old one would cause collisions). The encrypted config
blob is decrypted, the embedded ``generation_id`` / qdrant collection
fields are rewritten to the new id, and the result is re-encrypted under
a fresh ``config:{new_id}`` key + xadd'd onto ``tasks:docgen``.
"""

from __future__ import annotations

import json
from typing import Any
import uuid
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis
import structlog

from source2doc.security.encryption import ConfigEncryption

from app.routes.codetours.dependencies import get_encryption
from app.routes.streams import dependencies as streams_deps
from app.routes.tasks import dto as tasks_dto
from app.routes.tasks import service as tasks_service
from app.security.admin import require_admin


logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_admin)],
)


@router.post(
    "/{generation_id}/retry",
    response_model=tasks_dto.RetryTaskResponse,
)
async def retry_task_route(
    generation_id: UUID,
    redis: aioredis.Redis = Depends(streams_deps.get_redis),
    encryption: ConfigEncryption = Depends(get_encryption),
) -> tasks_dto.RetryTaskResponse:
    return await _retry_task(generation_id, redis, encryption)


async def _retry_task(
    generation_id: UUID,
    redis: aioredis.Redis,
    encryption: ConfigEncryption,
) -> tasks_dto.RetryTaskResponse:
    old_id = str(generation_id)

    # Locate the original task_stream — needed to find the matching DLQ
    # entry. We pull it from the ``task.failed`` event when present,
    # falling back to the conventional default so users can still retry
    # legacy generations that pre-date the ``task_stream`` field.
    task_stream = await _find_task_stream(redis, old_id)
    if task_stream is None:
        task_stream = tasks_service.TASKS_STREAM

    # Recover the full original payload. Prefer the DLQ entry — it's the
    # canonical record after retries are exhausted. Fall back to a direct
    # ``config:{old_id}`` lookup when the message hasn't reached DLQ yet
    # (handler-error path before max_retries).
    original_payload = await _find_dlq_payload(redis, task_stream, old_id)

    encrypted_config: str | None = None
    if original_payload is not None:
        old_config_key = original_payload.get("config_key")
        if isinstance(old_config_key, str):
            encrypted_config = await redis.get(old_config_key)

    if encrypted_config is None:
        # No DLQ entry hit, or the DLQ entry's config_key has expired
        # (TTL 86400). Try the conventional key directly.
        encrypted_config = await redis.get(f"config:{old_id}")

    if encrypted_config is None:
        logger.warning(
            "retry_task_unrecoverable",
            generation_id=old_id,
            task_stream=task_stream,
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot retry — original task payload not recoverable "
                "(DLQ may have been trimmed or the encrypted config has expired)"
            ),
        )

    user_config = encryption.decrypt_config(encrypted_config)

    new_generation_id = uuid4()
    new_trace_id = uuid.uuid4().hex
    new_qdrant_collection = f"docgen_{new_generation_id}"

    # Rewrite the per-generation fields. Everything else (LLM, embeddings,
    # qdrant URL/api_key, postgres, generation tunables, agents,
    # force_reindex, repo_id) is reused verbatim — that's the whole point
    # of "retry with same parameters".
    user_config["generation_id"] = str(new_generation_id)
    if isinstance(user_config.get("qdrant"), dict):
        user_config["qdrant"]["collection"] = new_qdrant_collection

    new_encrypted_config = encryption.encrypt_config(user_config)
    new_config_key = f"config:{new_generation_id}"
    await redis.setex(new_config_key, 86400, new_encrypted_config)

    await tasks_service._ensure_consumer_group(
        redis,
        tasks_service.TASKS_STREAM,
        tasks_service.TASKS_CONSUMER_GROUP,
    )

    # Recover the human-readable name and the per-task force_reindex flag
    # from the prior payload so the worker's ingest handler can read them
    # off the stream entry without decrypting the config blob (mirrors
    # ``create_task``).
    name_value = (
        original_payload.get("name")
        if original_payload is not None
        else user_config.get("name")
    )
    force_reindex_value = (
        original_payload.get("force_reindex")
        if original_payload is not None
        else user_config.get("force_reindex", False)
    )

    await redis.xadd(
        tasks_service.TASKS_STREAM,
        {
            "type": "task.created",
            "data": json.dumps(
                {
                    "generation_id": str(new_generation_id),
                    "trace_id": new_trace_id,
                    "config_key": new_config_key,
                    "qdrant_collection": new_qdrant_collection,
                    "name": name_value,
                    "force_reindex": bool(force_reindex_value),
                }
            ),
        },
    )

    logger.info(
        "task_retry_enqueued",
        retried_from=old_id,
        generation_id=str(new_generation_id),
        task_stream=task_stream,
    )

    return tasks_dto.RetryTaskResponse(
        generation_id=new_generation_id,
        retried_from=old_id,
        trace_id=new_trace_id,
        status="queued",
        message="Retry queued. Workers will pick it up shortly.",
        stream_url=f"/api/v1/streams/{new_generation_id}/stream",
        events_url=f"/api/v1/streams/{new_generation_id}/events",
    )


async def _find_task_stream(redis: aioredis.Redis, generation_id: str) -> str | None:
    """Read ``task_stream`` off the most recent ``task.failed`` event.

    Returns ``None`` when the events stream is missing, has been trimmed,
    or carries no ``task.failed`` entry. Callers should fall back to the
    default docgen task stream in that case.
    """
    try:
        entries = await redis.xrevrange(
            f"events:{generation_id}", "+", "-", count=200
        )
    except aioredis.ResponseError:
        return None

    for _entry_id, fields in entries:
        if fields.get("type") != "task.failed":
            continue
        try:
            data = json.loads(fields.get("data", "{}"))
        except json.JSONDecodeError:
            continue
        task_stream = data.get("task_stream")
        if isinstance(task_stream, str) and task_stream:
            return task_stream
    return None


async def _find_dlq_payload(
    redis: aioredis.Redis,
    task_stream: str,
    generation_id: str,
) -> dict[str, Any] | None:
    """Scan ``dlq:{task_stream}`` for the entry matching ``generation_id``.

    DLQ entries are written by ``worker.streams.consumer._move_to_dlq``
    with shape ``{type: "task.failed", data: <json>}``. The inner JSON
    carries ``data`` — the original stream payload (already parsed to a
    dict) including ``generation_id``, ``config_key``, etc.

    Returns the inner *task* payload dict (i.e. the contents of
    ``original.data``), not the DLQ envelope, so callers can read
    ``config_key`` / ``name`` / ``force_reindex`` directly.
    """
    dlq_stream = f"dlq:{task_stream}"
    try:
        # Newest-first: failures are usually retried right after they
        # happen, so the matching entry is near the head.
        entries = await redis.xrevrange(dlq_stream, "+", "-", count=500)
    except aioredis.ResponseError:
        return None

    for _entry_id, fields in entries:
        try:
            envelope = json.loads(fields.get("data", "{}"))
        except json.JSONDecodeError:
            continue
        inner = envelope.get("data")
        if not isinstance(inner, dict):
            continue
        if inner.get("generation_id") == generation_id:
            return inner
    return None
