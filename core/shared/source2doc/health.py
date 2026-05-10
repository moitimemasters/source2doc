"""Liveness probes for infrastructure dependencies.

Reusable async helpers for the gateway ``/health`` endpoint and any other
component that needs to surface dependency status. Every probe is wrapped
in ``asyncio.wait_for`` so a hung dep cannot block the caller.

Probes return a small ``ProbeResult`` dataclass — callers decide how to
serialize it (the gateway flattens to ``"ok"|"fail"`` strings).
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import typing as tp

from source2doc.config import QdrantConfig, S3Config
from source2doc.logging import get_logger


logger = get_logger(__name__)


DEFAULT_PROBE_TIMEOUT_S: float = 2.0


@dc.dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single liveness probe."""

    ok: bool
    error: str | None = None

    def as_status(self) -> str:
        return "ok" if self.ok else "fail"


async def _run_probe(
    name: str,
    coro: tp.Awaitable[tp.Any],
    timeout_s: float,
) -> ProbeResult:
    try:
        await asyncio.wait_for(coro, timeout=timeout_s)
        return ProbeResult(ok=True)
    except TimeoutError:
        logger.warning("health_probe_timeout", probe=name, timeout_s=timeout_s)
        return ProbeResult(ok=False, error=f"timeout after {timeout_s}s")
    except Exception as exc:  # noqa: BLE001 — probe must not raise
        logger.warning("health_probe_failed", probe=name, error=str(exc))
        return ProbeResult(ok=False, error=str(exc))


async def check_redis(
    redis_client: tp.Any,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
) -> ProbeResult:
    """PING the supplied redis.asyncio client."""
    return await _run_probe("redis", redis_client.ping(), timeout_s)


async def check_postgres(
    pg_storage: tp.Any,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
) -> ProbeResult:
    """``SELECT 1`` against the asyncpg pool of a PostgresStorage-like object."""

    async def _probe() -> None:
        pool = getattr(pg_storage, "pool", None)
        if pool is None:
            raise RuntimeError("postgres pool is not initialized")
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

    return await _run_probe("postgres", _probe(), timeout_s)


async def check_qdrant(
    config: QdrantConfig,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
) -> ProbeResult:
    """List collections via a short-lived AsyncQdrantClient.

    Qdrant has no shared client in gateway state today, so we open a probe
    client per call. The HTTP keep-alive is closed when the function exits.
    """

    async def _probe() -> None:
        # Imported lazily so non-qdrant components do not pay the import cost.
        import qdrant_client

        client = qdrant_client.AsyncQdrantClient(
            url=config.url,
            api_key=config.api_key,
            timeout=timeout_s,
        )
        try:
            await client.get_collections()
        finally:
            await client.close()

    return await _run_probe("qdrant", _probe(), timeout_s)


async def check_s3(
    config: S3Config,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
) -> ProbeResult:
    """``head_bucket`` against the configured S3 / LocalStack endpoint."""

    async def _probe() -> None:
        # Imported lazily because aioboto3 has a heavy import cost.
        import aioboto3

        session = aioboto3.Session(
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
        )
        async with session.client("s3", endpoint_url=config.endpoint_url) as s3:
            await s3.head_bucket(Bucket=config.bucket)

    return await _run_probe("s3", _probe(), timeout_s)
