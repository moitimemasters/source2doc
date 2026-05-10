"""Gateway /health integration tests.

PMI-mapping: РЗВ-03 (liveness probe surface for the gateway).

The route delegates probes to ``source2doc.health``. We monkeypatch those
helpers so the test does not need real Postgres / Qdrant / S3 — only the
fakeredis client and asyncpg-mock from conftest.
"""

from __future__ import annotations

from httpx import AsyncClient
import pytest

from source2doc.health import ProbeResult


async def test_health_ok_when_all_probes_pass(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok(*_args, **_kwargs) -> ProbeResult:
        return ProbeResult(ok=True)

    monkeypatch.setattr("app.routes.health.check_postgres", _ok)
    monkeypatch.setattr("app.routes.health.check_redis", _ok)
    monkeypatch.setattr("app.routes.health.check_qdrant", _ok)
    monkeypatch.setattr("app.routes.health.check_s3", _ok)

    response = await client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["components"] == {
        "postgres": "ok",
        "redis": "ok",
        "qdrant": "ok",
        "s3": "ok",
    }


async def test_health_degraded_when_any_probe_fails(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok(*_args, **_kwargs) -> ProbeResult:
        return ProbeResult(ok=True)

    async def _fail(*_args, **_kwargs) -> ProbeResult:
        return ProbeResult(ok=False, error="connection refused")

    monkeypatch.setattr("app.routes.health.check_postgres", _ok)
    monkeypatch.setattr("app.routes.health.check_redis", _ok)
    monkeypatch.setattr("app.routes.health.check_qdrant", _fail)
    monkeypatch.setattr("app.routes.health.check_s3", _ok)

    response = await client.get("/health")
    # The intentionally-tightened endpoint returns 503 when any probe fails so
    # an orchestrator can react without parsing the body.
    assert response.status_code == 503

    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["qdrant"].startswith("error")
    assert body["components"]["postgres"] == "ok"
