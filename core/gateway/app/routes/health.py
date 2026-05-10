"""Gateway liveness endpoint (closes ТЗ item РЗВ-03).

``GET /health`` probes Postgres, Redis, S3 and Qdrant concurrently. Each
probe has a short per-call timeout (see :mod:`source2doc.health`) so a
hung dependency cannot block the response.

Response shape::

    {
      "status": "ok" | "degraded",
      "components": {
        "postgres": "ok" | "error: <msg>",
        "redis":    "ok" | "error: <msg>",
        "s3":       "ok" | "error: <msg>",
        "qdrant":   "ok" | "error: <msg>"
      }
    }

HTTP status is ``200`` only when *every* probe succeeds; any failure
yields ``503`` with the same body shape so a caller can see exactly which
dep is degraded without scraping logs.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from source2doc.health import (
    DEFAULT_PROBE_TIMEOUT_S,
    ProbeResult,
    check_postgres,
    check_qdrant,
    check_redis,
    check_s3,
)


router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    components: dict[str, str]


def _component_status(result: ProbeResult) -> str:
    if result.ok:
        return "ok"
    return f"error: {result.error}" if result.error else "error"


async def _not_initialized(msg: str) -> ProbeResult:
    """Wrap the not-initialized branch as a coroutine so callers can ``gather``."""
    return ProbeResult(ok=False, error=msg)


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
)
async def health(request: Request) -> JSONResponse:
    config = request.app.state.config
    redis_client = getattr(request.app.state, "redis", None)
    pg_storage = getattr(request.app.state, "storage", None)

    # If lifespan failed to wire a client we still want a clear, structured
    # error rather than a 500. The probe helpers already coerce exceptions
    # into ProbeResult.
    redis_probe = (
        check_redis(redis_client, timeout_s=DEFAULT_PROBE_TIMEOUT_S)
        if redis_client is not None
        else _not_initialized("redis client not initialized")
    )
    postgres_probe = (
        check_postgres(pg_storage, timeout_s=DEFAULT_PROBE_TIMEOUT_S)
        if pg_storage is not None
        else _not_initialized("postgres storage not initialized")
    )

    postgres_res, redis_res, s3_res, qdrant_res = await asyncio.gather(
        postgres_probe,
        redis_probe,
        check_s3(config.s3, timeout_s=DEFAULT_PROBE_TIMEOUT_S),
        check_qdrant(config.qdrant, timeout_s=DEFAULT_PROBE_TIMEOUT_S),
    )

    components = {
        "postgres": _component_status(postgres_res),
        "redis": _component_status(redis_res),
        "s3": _component_status(s3_res),
        "qdrant": _component_status(qdrant_res),
    }
    all_ok = all(r.ok for r in (postgres_res, redis_res, s3_res, qdrant_res))
    payload = HealthResponse(
        status="ok" if all_ok else "degraded",
        components=components,
    )
    status_code = 200 if all_ok else 503
    return JSONResponse(status_code=status_code, content=payload.model_dump())
