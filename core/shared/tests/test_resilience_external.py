"""Tenacity-based external retry decorator tests.

Asserts that ``s3_retry`` and ``qdrant_retry`` retry on transient (5xx /
network) failures and immediately reraise on 4xx / non-transient errors.
"""

from __future__ import annotations

import asyncio
import typing as tp

import httpx
import pytest

from source2doc.resilience import qdrant_retry, s3_retry


class _FakeBotocoreClientError(Exception):
    """Mimics ``botocore.exceptions.ClientError`` for predicate matching.

    The real ClientError lives behind an aioboto3 import that we don't want
    to require in the unit-test path; the predicate uses ``isinstance`` so
    we patch the predicate's import target via the lazy-import path.
    """

    def __init__(self, status: int) -> None:
        super().__init__(f"client_error_{status}")
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}, "Error": {}}


@pytest.fixture
def patch_botocore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``botocore.exceptions.ClientError`` resolve to our fake.

    The decorator does ``from botocore import exceptions`` lazily inside the
    predicate. We swap the attribute so ``isinstance`` matches our fake.
    """
    import botocore.exceptions as botocore_exc

    monkeypatch.setattr(botocore_exc, "ClientError", _FakeBotocoreClientError, raising=False)


@pytest.mark.asyncio
async def test_s3_retry_retries_on_5xx_then_succeeds(patch_botocore: None) -> None:
    calls: list[int] = []

    @s3_retry(max_attempts=3, max_total_seconds=5.0)
    async def fn() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise _FakeBotocoreClientError(503)
        return "ok"

    assert await fn() == "ok"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_s3_retry_does_not_retry_on_4xx(patch_botocore: None) -> None:
    calls: list[int] = []

    @s3_retry(max_attempts=5, max_total_seconds=5.0)
    async def fn() -> None:
        calls.append(1)
        raise _FakeBotocoreClientError(403)

    with pytest.raises(_FakeBotocoreClientError):
        await fn()
    # 4xx is non-retryable: must fire exactly once.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_s3_retry_retries_on_httpx_transport_error() -> None:
    calls: list[int] = []

    @s3_retry(max_attempts=3, max_total_seconds=5.0)
    async def fn() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise httpx.ConnectError("boom")
        return "ok"

    assert await fn() == "ok"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_s3_retry_exhausts_attempts_and_reraises(patch_botocore: None) -> None:
    calls: list[int] = []

    @s3_retry(max_attempts=3, max_total_seconds=5.0)
    async def fn() -> None:
        calls.append(1)
        raise _FakeBotocoreClientError(500)

    with pytest.raises(_FakeBotocoreClientError):
        await fn()
    assert len(calls) == 3


class _FakeQdrantUnexpectedResponse(Exception):
    """Stand-in for ``qdrant_client.http.exceptions.UnexpectedResponse``."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"qdrant_{status_code}")
        self.status_code = status_code


@pytest.fixture
def patch_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
    from qdrant_client.http import exceptions as qdrant_exc

    monkeypatch.setattr(
        qdrant_exc, "UnexpectedResponse", _FakeQdrantUnexpectedResponse, raising=False
    )


@pytest.mark.asyncio
async def test_qdrant_retry_retries_on_5xx(patch_qdrant: None) -> None:
    calls: list[int] = []

    @qdrant_retry(max_attempts=3, max_total_seconds=5.0)
    async def fn() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise _FakeQdrantUnexpectedResponse(502)
        return "ok"

    assert await fn() == "ok"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_qdrant_retry_does_not_retry_on_4xx(patch_qdrant: None) -> None:
    calls: list[int] = []

    @qdrant_retry(max_attempts=5, max_total_seconds=5.0)
    async def fn() -> None:
        calls.append(1)
        raise _FakeQdrantUnexpectedResponse(404)

    with pytest.raises(_FakeQdrantUnexpectedResponse):
        await fn()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_uses_instance_resilience_override() -> None:
    """When the decorated method's ``self.resilience`` is set, attempts come from there."""

    class _Stub:
        def __init__(self, max_attempts: int, max_total_seconds: float) -> None:
            class _Cfg:
                pass

            cfg = _Cfg()
            cfg.max_attempts = max_attempts
            cfg.max_total_seconds = max_total_seconds
            self.resilience = cfg
            self.calls: list[int] = []

        @s3_retry(max_attempts=10, max_total_seconds=999.0)
        async def call(self) -> tp.NoReturn:
            self.calls.append(1)
            raise httpx.ConnectError("never")

    stub = _Stub(max_attempts=2, max_total_seconds=5.0)
    with pytest.raises(httpx.ConnectError):
        await stub.call()
    # Instance override caps at 2 attempts even though the decorator declared 10.
    assert len(stub.calls) == 2


@pytest.mark.asyncio
async def test_retry_runs_concurrently_independent_calls() -> None:
    """Two concurrent retry-wrapped calls don't share state."""

    @s3_retry(max_attempts=2, max_total_seconds=5.0)
    async def succeed() -> str:
        return "ok"

    results = await asyncio.gather(succeed(), succeed(), succeed())
    assert results == ["ok", "ok", "ok"]
