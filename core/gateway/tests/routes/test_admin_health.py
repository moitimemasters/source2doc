"""Aggregate admin health endpoint tests.

PMI-mapping: МНТ-09 / B4.2 (UI health indicators for all components).

The route fans out to the existing dependency probes plus per-worker
HTTP /health URLs. We monkeypatch the dependency probes (already done in
``test_health.py``) and stub ``httpx.AsyncClient`` so the test does not
need real workers running.
"""

from __future__ import annotations

import httpx
from httpx import AsyncClient
import pytest

from source2doc.health import ProbeResult

from app.routes.admin.health import router as admin_health_router_mod


@pytest.fixture(autouse=True)
def _reset_admin_health_cache():
    """The aggregate endpoint caches results for 5s; isolate tests."""
    admin_health_router_mod._reset_cache_for_tests()
    yield
    admin_health_router_mod._reset_cache_for_tests()


class _StubAsyncClient:
    """Minimal httpx.AsyncClient drop-in for worker probes."""

    def __init__(self, responses: dict[str, httpx.Response | Exception]):
        self._responses = responses

    async def __aenter__(self) -> _StubAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, timeout: float | None = None) -> httpx.Response:
        result = self._responses.get(url)
        if result is None:
            raise httpx.ConnectError(f"no stub for {url}")
        if isinstance(result, Exception):
            raise result
        return result


def _stub_httpx(monkeypatch: pytest.MonkeyPatch, responses: dict[str, object]) -> None:
    monkeypatch.setattr(
        admin_health_router_mod.httpx,
        "AsyncClient",
        lambda *a, **kw: _StubAsyncClient(responses),
    )


def _ok_response(status: str = "ok") -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"status": status, "worker": "test", "worker_id": "test-1"},
    )


def _stale_response() -> httpx.Response:
    return httpx.Response(
        status_code=503,
        json={"status": "stale", "worker": "test", "worker_id": "test-1"},
    )


def _patch_dep_probes(monkeypatch: pytest.MonkeyPatch, *, all_ok: bool = True) -> None:
    async def _ok(*_args, **_kwargs) -> ProbeResult:
        return ProbeResult(ok=True)

    async def _fail(*_args, **_kwargs) -> ProbeResult:
        return ProbeResult(ok=False, error="connection refused")

    target = _ok if all_ok else _fail
    monkeypatch.setattr("app.routes.admin.health.router.check_postgres", _ok)
    monkeypatch.setattr("app.routes.admin.health.router.check_redis", _ok)
    monkeypatch.setattr("app.routes.admin.health.router.check_qdrant", target)
    monkeypatch.setattr("app.routes.admin.health.router.check_s3", _ok)


async def test_components_all_ok(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dep_probes(monkeypatch, all_ok=True)
    _stub_httpx(
        monkeypatch,
        {
            "http://worker-docgen:8100/health": _ok_response(),
            "http://worker-repos:8101/health": _ok_response(),
            "http://worker-bundler:8102/health": _ok_response(),
            "http://worker-codetour:8103/health": _ok_response(),
        },
    )

    response = await client.get("/api/v1/admin/health/components")
    assert response.status_code == 200
    body = response.json()
    assert set(body["components"].keys()) == {
        "postgres",
        "redis",
        "s3",
        "qdrant",
        "worker-docgen",
        "worker-repos",
        "worker-bundler",
        "worker-codetour",
    }
    assert all(v == "ok" for v in body["components"].values())
    # checked_at is an ISO-8601 string ending in Z
    assert body["checked_at"].endswith("Z")


async def test_components_worker_down(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dep_probes(monkeypatch, all_ok=True)
    _stub_httpx(
        monkeypatch,
        {
            "http://worker-docgen:8100/health": _ok_response(),
            "http://worker-repos:8101/health": httpx.ConnectError("refused"),
            "http://worker-bundler:8102/health": _ok_response(),
            "http://worker-codetour:8103/health": _ok_response(),
        },
    )

    response = await client.get("/api/v1/admin/health/components")
    assert response.status_code == 200  # the endpoint always returns 200
    body = response.json()
    assert body["components"]["worker-repos"].startswith("error")
    assert body["components"]["worker-docgen"] == "ok"


async def test_components_worker_stale(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dep_probes(monkeypatch, all_ok=True)
    _stub_httpx(
        monkeypatch,
        {
            "http://worker-docgen:8100/health": _stale_response(),
            "http://worker-repos:8101/health": _ok_response(),
            "http://worker-bundler:8102/health": _ok_response(),
            "http://worker-codetour:8103/health": _ok_response(),
        },
    )

    response = await client.get("/api/v1/admin/health/components")
    assert response.status_code == 200
    body = response.json()
    # 503 from worker carries a "stale" status payload.
    assert body["components"]["worker-docgen"].startswith("error")
    assert "503" in body["components"]["worker-docgen"]


async def test_components_dependency_degraded(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dep_probes(monkeypatch, all_ok=False)
    _stub_httpx(
        monkeypatch,
        {
            "http://worker-docgen:8100/health": _ok_response(),
            "http://worker-repos:8101/health": _ok_response(),
            "http://worker-bundler:8102/health": _ok_response(),
            "http://worker-codetour:8103/health": _ok_response(),
        },
    )

    response = await client.get("/api/v1/admin/health/components")
    assert response.status_code == 200
    body = response.json()
    assert body["components"]["qdrant"].startswith("error")


async def test_components_uses_env_override(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dep_probes(monkeypatch, all_ok=True)
    monkeypatch.setenv("WORKER_DOCGEN_HEALTH_URL", "http://override:9000/health")
    _stub_httpx(
        monkeypatch,
        {
            "http://override:9000/health": _ok_response(),
            "http://worker-repos:8101/health": _ok_response(),
            "http://worker-bundler:8102/health": _ok_response(),
            "http://worker-codetour:8103/health": _ok_response(),
        },
    )

    response = await client.get("/api/v1/admin/health/components")
    assert response.status_code == 200
    assert response.json()["components"]["worker-docgen"] == "ok"


async def test_components_caches_response(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_dep_probes(monkeypatch, all_ok=True)

    call_count = {"n": 0}

    class CountingClient(_StubAsyncClient):
        async def get(self, url: str, timeout: float | None = None) -> httpx.Response:
            call_count["n"] += 1
            return _ok_response()

    monkeypatch.setattr(
        admin_health_router_mod.httpx,
        "AsyncClient",
        lambda *a, **kw: CountingClient({}),
    )

    first = await client.get("/api/v1/admin/health/components")
    second = await client.get("/api/v1/admin/health/components")
    assert first.status_code == 200
    assert second.status_code == 200
    # Two polls, but only one actual fan-out happened (4 worker probes).
    assert call_count["n"] == 4
    # checked_at should be identical for the cached response.
    assert first.json()["checked_at"] == second.json()["checked_at"]
