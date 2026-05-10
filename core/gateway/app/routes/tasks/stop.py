"""User-initiated stop endpoint.

``POST /api/v1/tasks/{generation_id}/stop`` flips the generation's
``cancelled`` flag in Redis state and emits a ``task.failed`` audit
marker. The docgen worker dispatcher reads ``state.cancelled`` before
each handler invocation and skip+acks pending messages, so further
LLM-heavy work (writer, diagrammer, critic) stops without burning more
tokens. Already-issued LLM HTTP requests run to completion (we don't
abort in-flight httpx calls) — typical max wait ≈ one agent.run cycle
of 30-60 s before the worker fully drains.

Resume re-emits an upstream ``*.completed`` event AND clears the
``cancelled`` flag, so the same generation can be picked up later if
the user changes their mind.

Why a server-side flag instead of just XDEL'ing the stream
----------------------------------------------------------
Killing the stream would lose the audit trail (events emitted before
stop). The flag-based approach lets us preserve all history in
``events:{gen_id}`` and rely on the same Redis-backed status
derivation that drives the rest of the UI: a fresh ``task.failed`` at
the top of the stream → status flips to "failed" → red banner with
Resume / Restart buttons appears.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis
import structlog

from app.routes.streams import dependencies as streams_deps
from app.security.admin import require_admin


logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_admin)],
)


@router.post(
    "/{generation_id}/stop",
    response_model=None,
)
async def stop_task_route(
    generation_id: UUID,
    redis: aioredis.Redis = Depends(streams_deps.get_redis),
) -> dict[str, Any]:
    return await _stop_task(generation_id, redis)


async def _stop_task(
    generation_id: UUID,
    redis: aioredis.Redis,
) -> dict[str, Any]:
    gen_id = str(generation_id)
    state_key = f"state:docgen:{gen_id}"
    events_stream = f"events:{gen_id}"

    # Need at least the state key to be present — without it the worker
    # wouldn't know what we're cancelling. Stale state TTL (24h) makes
    # this a soft check; if state has expired the gen is effectively
    # done from the worker's perspective anyway.
    state_exists = bool(await redis.exists(state_key))
    if not state_exists:
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot stop — no worker state for this generation. "
                "Either it never started, already finished, or its state "
                "key (24h TTL) has been evicted."
            ),
        )

    # Flip the flag. The worker dispatcher reads this before every
    # handler call; pending messages get skip+acked instead of running
    # the writer / critic / diagrammer agent.
    await redis.hset(state_key, "cancelled", "true")

    # Audit marker. ``task.stopped`` is its own terminal event type
    # (kind=TERMINAL in the DOCGEN registry), distinct from
    # ``task.failed``. The streams service derives status from the
    # newest event, so a fresh ``task.stopped`` flips the run to
    # ``stopped`` (not "failed") — a separate UI state with a Resume
    # button but a less alarming banner colour, since the user
    # explicitly chose to halt.
    await redis.xadd(
        events_stream,
        {
            "type": "task.stopped",
            "data": json.dumps(
                {
                    "generation_id": gen_id,
                    "reason": "user_cancelled",
                    "phase": "finalize",
                    "kind": "terminal",
                }
            ),
        },
    )

    logger.info("task_stop_requested", generation_id=gen_id)

    return {
        "generation_id": gen_id,
        "status": "stopped",
        "message": (
            "Cancellation flag set. Worker will skip pending events for this "
            "generation; in-flight LLM calls finish naturally. Use Resume to "
            "continue from the last successful checkpoint."
        ),
        "stream_url": f"/api/v1/streams/{gen_id}/stream",
        "events_url": f"/api/v1/streams/{gen_id}/events",
    }
