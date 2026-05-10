"""Admin metrics for cluster-wide LLM session locks.

Returns a snapshot of every ``llm:sessions:{api_key_hash}`` Redis ZSET
the workers are using to throttle parallel ``agent.run`` invocations.
Surfaces:

* The api_key hash (first 16 hex chars of sha256 — never the raw key)
* How many slots are currently in use vs the configured cap
* For each held slot: which worker process holds it, the agent role,
  and how long ago it was acquired

Read-only and admin-gated. Refresh interval on the UI side is whatever
the page chooses (5 s polling is a reasonable default).
"""

from __future__ import annotations

import time
import typing as tp

from fastapi import APIRouter, Depends
import redis.asyncio as aioredis

from app.routes.streams import dependencies as streams_deps
from app.security.admin import require_admin


router = APIRouter(
    prefix="/api/v1/admin/llm-sessions",
    tags=["admin", "llm-sessions"],
    dependencies=[Depends(require_admin)],
)


_KEY_PREFIX = "llm:sessions:"


def _parse_token(token: str) -> dict[str, str]:
    """Token format: ``{label}|{nonce}`` where label is
    ``{worker_id}:{agent_role}``. Returns parsed parts; missing pieces
    are surfaced as empty strings so the UI can render a uniform table.
    """
    if "|" not in token:
        return {"worker_id": "", "role": "", "nonce": token}
    label, _, nonce = token.partition("|")
    if ":" in label:
        worker_id, _, role = label.partition(":")
    else:
        worker_id = label
        role = ""
    return {"worker_id": worker_id, "role": role, "nonce": nonce}


@router.get("")
async def list_llm_sessions(
    redis: aioredis.Redis = Depends(streams_deps.get_redis),
) -> dict[str, tp.Any]:
    keys: list[str] = []
    async for key in redis.scan_iter(match=f"{_KEY_PREFIX}*"):
        keys.append(key)

    now_ms = int(time.time() * 1000)
    out: list[dict[str, tp.Any]] = []
    for key in sorted(keys):
        api_key_hash = key[len(_KEY_PREFIX) :]
        # ZSET members + scores. Members are tokens, scores are
        # acquisition-time-ms (refreshed by heartbeat every 30 s).
        raw = await redis.zrange(key, 0, -1, withscores=True)
        ttl_ms = await redis.pttl(key)
        members: list[dict[str, tp.Any]] = []
        for tok, score in raw:
            parts = _parse_token(tok)
            age_ms = max(0, now_ms - int(score))
            members.append(
                {
                    "token": tok,
                    "worker_id": parts["worker_id"],
                    "role": parts["role"],
                    "age_seconds": age_ms / 1000.0,
                    "acquired_at_ms": int(score),
                }
            )
        out.append(
            {
                "api_key_hash": api_key_hash,
                "active": len(members),
                # We don't know the configured ``max_sessions`` from the
                # ZSET alone — that lives in per-task user_config. The
                # UI displays "active / ?" until we plumb the cap;
                # operationally that's fine because the lock script
                # rejects past the cap anyway.
                "key_ttl_ms": ttl_ms if ttl_ms > 0 else None,
                "members": members,
            }
        )

    return {"sessions": out, "scanned_at_ms": now_ms}
