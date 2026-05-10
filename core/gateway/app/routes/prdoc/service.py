"""Gateway service for PR microdoc requests.

Encrypts the user-supplied LLM (and optional embeddings/qdrant) config,
inserts a ``prdoc_summaries`` row in ``pending`` status, then publishes a
``tasks:prdoc`` Redis Streams message for the worker to pick up.
"""

from __future__ import annotations

import json
import secrets
import typing as tp
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import BaseModel, SecretStr
import redis.asyncio as aioredis

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.prdoc import PRDocStorage
from source2doc.storage.presets import ConfigPresetStorage

from app.errors import ResourceNotFoundError
from app.routes.prdoc.dto import (
    AdminPRDocRequest,
    PRDocRequest,
    PRDocResponse,
    PRDocResult,
)


PRDOC_STREAM = "tasks:prdoc"
PRDOC_CONSUMER_GROUP = "prdoc-workers"
CONFIG_TTL_SECONDS = 24 * 3600
EVENTS_TTL_SECONDS = 24 * 3600


def _config_key(generation_id: UUID) -> str:
    return f"config:prdoc:{generation_id}"


def _events_stream(generation_id: UUID) -> str:
    return f"events:prdoc:{generation_id}"


def _model_to_serializable(model: BaseModel | None) -> dict[str, tp.Any] | None:
    if model is None:
        return None
    out: dict[str, tp.Any] = {}
    for key, value in model.model_dump(exclude_none=False).items():
        if isinstance(value, SecretStr):
            out[key] = value.get_secret_value()
        else:
            out[key] = value
    for field_name in model.model_fields:
        attr = getattr(model, field_name, None)
        if isinstance(attr, SecretStr):
            out[field_name] = attr.get_secret_value()
    return out


async def _resolve_prdoc_configs(
    *,
    request: PRDocRequest | AdminPRDocRequest,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> dict[str, tp.Any]:
    """Pick LLM/embeddings/qdrant from preset + admin overrides.

    Unlike ``resolve_configs`` (which is shared with codetour and demands
    embeddings up front), this resolver tolerates a missing embeddings
    block: PR microdoc only needs them when ``repo_id`` is set and RAG is
    actually requested. The worker re-checks at run time.
    """

    is_admin = isinstance(request, AdminPRDocRequest)
    base: dict[str, tp.Any] = {}

    preset_name = request.preset if is_admin else None
    if preset_name:
        preset = await presets.get_by_name(preset_name)
        if not preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preset '{preset_name}' not found",
            )
        base = encryption.decrypt_config(preset.encrypted_config)
    else:
        default = await presets.get_default()
        if default:
            base = encryption.decrypt_config(default.encrypted_config)

    request_llm = _model_to_serializable(request.llm) if is_admin else None
    request_embeddings = _model_to_serializable(request.embeddings) if is_admin else None
    request_qdrant = _model_to_serializable(request.qdrant) if is_admin else None

    llm = request_llm or base.get("llm")
    embeddings = request_embeddings or base.get("embeddings")
    qdrant = request_qdrant or base.get("qdrant")

    if not llm:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No LLM config available. Configure a default preset via "
                "/admin/presets or supply `llm` in the request."
            ),
        )

    resolved: dict[str, tp.Any] = {"llm": llm}
    if embeddings:
        resolved["embeddings"] = embeddings
    if qdrant:
        resolved["qdrant"] = qdrant
    return resolved


async def create_prdoc(
    request: PRDocRequest | AdminPRDocRequest,
    redis: aioredis.Redis,
    encryption: ConfigEncryption,
    storage: PRDocStorage,
    presets: ConfigPresetStorage,
) -> PRDocResponse:
    generation_id = uuid4()
    trace_id = secrets.token_hex(8)
    config_key = _config_key(generation_id)

    resolved = await _resolve_prdoc_configs(
        request=request,
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

    await storage.create_pending(
        generation_id=generation_id,
        repo_id=request.repo_id,
        base_sha=request.base_sha,
        head_sha=request.head_sha,
        title=request.title,
    )

    await _ensure_consumer_group(redis, PRDOC_STREAM, PRDOC_CONSUMER_GROUP)

    # Mirror the requested event into the per-generation stream so SSE
    # clients see ``prdoc.requested`` immediately, before the worker has
    # picked the task up.
    events_stream = _events_stream(generation_id)
    requested_payload = {
        "generation_id": str(generation_id),
        "trace_id": trace_id,
        "repo_id": str(request.repo_id) if request.repo_id else None,
        "files_changed": len(request.changed_files),
    }
    await redis.xadd(
        events_stream,
        {"type": "prdoc.requested", "data": json.dumps(requested_payload)},
    )
    await redis.expire(events_stream, EVENTS_TTL_SECONDS)

    await redis.xadd(
        PRDOC_STREAM,
        {
            "type": "prdoc.requested",
            "data": json.dumps(
                {
                    "generation_id": str(generation_id),
                    "trace_id": trace_id,
                    "config_key": config_key,
                    "repo_id": str(request.repo_id) if request.repo_id else None,
                    "base_sha": request.base_sha,
                    "head_sha": request.head_sha,
                    "title": request.title,
                    "description": request.description,
                    "changed_files": [f.model_dump() for f in request.changed_files],
                }
            ),
        },
    )

    return PRDocResponse(
        generation_id=generation_id,
        trace_id=trace_id,
        status="pending",
        message="PR microdoc generation started",
    )


async def get_prdoc(
    generation_id: UUID,
    storage: PRDocStorage,
) -> PRDocResult:
    record = await storage.get(generation_id)
    if record is None:
        raise ResourceNotFoundError(resource_type="prdoc", resource_id=str(generation_id))
    return PRDocResult(**record)


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
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
