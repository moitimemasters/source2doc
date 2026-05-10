"""Aggregate health endpoint (closes ТЗ МНТ-09 / B4.2).

``GET /api/v1/admin/health/components`` fans out to:

* The gateway's own dependency probes (postgres / redis / s3 / qdrant) by
  calling the existing ``/health`` route's helpers in-process.
* Each worker's HTTP ``/health`` listener (docgen / repos / bundler /
  codetour) over the docker network.

Worker URLs are read from environment variables so deployments can
override the docker-compose defaults without rebuilding the image:

* ``WORKER_DOCGEN_HEALTH_URL``  (default ``http://worker-docgen:8100/health``)
* ``WORKER_REPOS_HEALTH_URL``   (default ``http://worker-repos:8101/health``)
* ``WORKER_BUNDLER_HEALTH_URL`` (default ``http://worker-bundler:8102/health``)
* ``WORKER_CODETOUR_HEALTH_URL``(default ``http://worker-codetour:8103/health``)

Each worker probe has a 2 second timeout and runs concurrently via
``asyncio.gather(..., return_exceptions=True)`` so a slow / dead worker
cannot delay the response.

Results are cached in-process for ``CACHE_TTL_S`` seconds to absorb
concurrent UI polls without hammering the workers — there is no point
re-probing on every poll when several browser tabs are open.
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import os
import time
import typing as tp

from fastapi import APIRouter, Depends, Request
import httpx
from pydantic import BaseModel

from source2doc.health import (
    DEFAULT_PROBE_TIMEOUT_S,
    ProbeResult,
    check_postgres,
    check_qdrant,
    check_redis,
    check_s3,
)
from source2doc.logging import get_logger

from app.security.admin import require_admin


logger = get_logger(__name__)


router = APIRouter(
    prefix="/api/v1/admin/health",
    tags=["admin:health"],
    dependencies=[Depends(require_admin)],
)


# Default docker-compose service hostnames + per-mode ports. Matches the
# `worker-*` services and their per-mode health ports declared in
# docker-compose.yml.
DEFAULT_WORKER_URLS: dict[str, str] = {
    "worker-docgen": "http://worker-docgen:8100/health",
    "worker-repos": "http://worker-repos:8101/health",
    "worker-bundler": "http://worker-bundler:8102/health",
    "worker-codetour": "http://worker-codetour:8103/health",
}

WORKER_ENV_VARS: dict[str, str] = {
    "worker-docgen": "WORKER_DOCGEN_HEALTH_URL",
    "worker-repos": "WORKER_REPOS_HEALTH_URL",
    "worker-bundler": "WORKER_BUNDLER_HEALTH_URL",
    "worker-codetour": "WORKER_CODETOUR_HEALTH_URL",
}

WORKER_PROBE_TIMEOUT_S: float = 2.0
CACHE_TTL_S: float = 5.0


class ComponentsHealthResponse(BaseModel):
    components: dict[str, str]
    checked_at: str


@dc.dataclass
class _CacheEntry:
    response: ComponentsHealthResponse
    expires_at: float


# Module-level cache. The gateway is a single FastAPI process per
# container; sharing one dict is fine and the entry is tiny.
_cache: _CacheEntry | None = None
_cache_lock = asyncio.Lock()


def _component_status(result: ProbeResult) -> str:
    if result.ok:
        return "ok"
    return f"error: {result.error}" if result.error else "error"


def _worker_urls() -> dict[str, str]:
    """Resolve per-worker /health URLs from env, falling back to the
    docker-compose defaults."""
    return {
        name: os.environ.get(env_var, DEFAULT_WORKER_URLS[name])
        for name, env_var in WORKER_ENV_VARS.items()
    }


async def _probe_worker(client: httpx.AsyncClient, url: str) -> ProbeResult:
    """Hit a worker /health URL and turn the response into a ProbeResult.

    A 2xx response counts as healthy. A 5xx (e.g. the worker's own 503 for
    a stale heartbeat) counts as an error and the body's status is surfaced.
    Network failures (DNS, connection refused, timeout) become
    ``error: <short msg>``.
    """
    try:
        response = await client.get(url, timeout=WORKER_PROBE_TIMEOUT_S)
    except httpx.TimeoutException:
        return ProbeResult(ok=False, error=f"timeout after {WORKER_PROBE_TIMEOUT_S}s")
    except httpx.HTTPError as exc:
        return ProbeResult(ok=False, error=f"http error: {exc.__class__.__name__}")
    except Exception as exc:  # noqa: BLE001 — never raise from a probe
        return ProbeResult(ok=False, error=str(exc))

    if 200 <= response.status_code < 300:
        return ProbeResult(ok=True)

    # Try to surface the worker's own status string when available, e.g.
    # "stale" from worker.health when the heartbeat is too old.
    detail = f"http {response.status_code}"
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("status"), str):
            detail = f"{detail} ({body['status']})"
    except (ValueError, TypeError):
        pass
    return ProbeResult(ok=False, error=detail)


async def _gather_dependency_probes(request: Request) -> dict[str, ProbeResult]:
    """Run the in-process gateway probes (postgres/redis/s3/qdrant)."""
    config = request.app.state.config
    redis_client = getattr(request.app.state, "redis", None)
    pg_storage = getattr(request.app.state, "storage", None)

    async def _not_initialized(msg: str) -> ProbeResult:
        return ProbeResult(ok=False, error=msg)

    redis_probe: tp.Awaitable[ProbeResult] = (
        check_redis(redis_client, timeout_s=DEFAULT_PROBE_TIMEOUT_S)
        if redis_client is not None
        else _not_initialized("redis client not initialized")
    )
    postgres_probe: tp.Awaitable[ProbeResult] = (
        check_postgres(pg_storage, timeout_s=DEFAULT_PROBE_TIMEOUT_S)
        if pg_storage is not None
        else _not_initialized("postgres storage not initialized")
    )

    postgres_res, redis_res, s3_res, qdrant_res = await asyncio.gather(
        postgres_probe,
        redis_probe,
        check_s3(config.s3, timeout_s=DEFAULT_PROBE_TIMEOUT_S),
        check_qdrant(config.qdrant, timeout_s=DEFAULT_PROBE_TIMEOUT_S),
        return_exceptions=False,
    )
    return {
        "postgres": postgres_res,
        "redis": redis_res,
        "s3": s3_res,
        "qdrant": qdrant_res,
    }


async def _gather_worker_probes() -> dict[str, ProbeResult]:
    """Probe every configured worker concurrently."""
    urls = _worker_urls()
    async with httpx.AsyncClient() as client:
        coros = [_probe_worker(client, url) for url in urls.values()]
        results = await asyncio.gather(*coros, return_exceptions=True)

    probes: dict[str, ProbeResult] = {}
    for name, result in zip(urls.keys(), results, strict=True):
        if isinstance(result, ProbeResult):
            probes[name] = result
        else:
            # asyncio.gather returned an exception object (shouldn't happen
            # because _probe_worker already swallows errors, but handle it
            # defensively so the endpoint never 500s).
            probes[name] = ProbeResult(ok=False, error=str(result))
    return probes


async def _build_response(request: Request) -> ComponentsHealthResponse:
    deps_task = asyncio.create_task(_gather_dependency_probes(request))
    workers_task = asyncio.create_task(_gather_worker_probes())
    deps, workers = await asyncio.gather(deps_task, workers_task)

    components: dict[str, str] = {}
    for name in ("postgres", "redis", "s3", "qdrant"):
        components[name] = _component_status(deps[name])
    for name in (
        "worker-docgen",
        "worker-repos",
        "worker-bundler",
        "worker-codetour",
    ):
        components[name] = _component_status(workers[name])

    return ComponentsHealthResponse(
        components=components,
        checked_at=dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
    )


@router.get("/components", response_model=ComponentsHealthResponse)
async def components_health(request: Request) -> ComponentsHealthResponse:
    """Aggregate gateway + worker health for the admin UI.

    Cached for ``CACHE_TTL_S`` seconds so concurrent browser polls don't
    fan out to every worker on every tick. The cache key is global — all
    admins see the same snapshot.
    """
    global _cache
    now = time.monotonic()

    cached = _cache
    if cached is not None and cached.expires_at > now:
        return cached.response

    async with _cache_lock:
        # Re-check inside the lock — another coroutine may have refreshed
        # the cache while we waited.
        cached = _cache
        now = time.monotonic()
        if cached is not None and cached.expires_at > now:
            return cached.response

        response = await _build_response(request)
        _cache = _CacheEntry(response=response, expires_at=now + CACHE_TTL_S)
        return response


def _reset_cache_for_tests() -> None:
    """Test hook — drop the in-memory cache between tests."""
    global _cache
    _cache = None
