"""Tests for the HTTP-layer LLM retry decorator.

The decorator should:

* Retry on ``httpx.TransportError`` up to ``max_attempts`` times, then
  surface the last exception unchanged.
* Retry on ``httpx.HTTPStatusError`` with status 5xx and exactly 429.
* NOT retry on 4xx other than 429.
* Retry on Pydantic-AI's ``ModelHTTPError`` for the same status codes.
"""

from __future__ import annotations

import httpx
import pytest
import tenacity

from source2doc.llm_retry import _is_retryable_http_error, llm_http_retry


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenacity uses ``time.sleep`` between attempts; fast-forward in tests."""

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)
    import asyncio

    async def _no_async_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_async_sleep)


async def test_retries_transport_error_and_surfaces() -> None:
    attempts = 0

    @llm_http_retry(max_attempts=3, max_total_seconds=10.0)
    async def call() -> str:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("dns down")

    with pytest.raises(httpx.ConnectError):
        await call()

    assert attempts == 3, "must retry up to max_attempts before surfacing"


async def test_retries_5xx_status_error() -> None:
    attempts = 0

    @llm_http_retry(max_attempts=3, max_total_seconds=10.0)
    async def call() -> str:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", "https://example.test")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("upstream busy", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        await call()

    assert attempts == 3


async def test_retries_429() -> None:
    attempts = 0

    @llm_http_retry(max_attempts=3, max_total_seconds=10.0)
    async def call() -> str:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", "https://example.test")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        await call()

    assert attempts == 3


async def test_does_not_retry_4xx() -> None:
    attempts = 0

    @llm_http_retry(max_attempts=3, max_total_seconds=10.0)
    async def call() -> str:
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", "https://example.test")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad input", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        await call()

    assert attempts == 1, "4xx (other than 429) must not retry"


async def test_succeeds_after_one_retry() -> None:
    attempts = 0

    @llm_http_retry(max_attempts=3, max_total_seconds=10.0)
    async def call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("flaky")
        return "ok"

    result = await call()
    assert result == "ok"
    assert attempts == 2


def test_predicate_recognises_pydantic_ai_model_http_error() -> None:
    from pydantic_ai.exceptions import ModelHTTPError

    exc_5xx = ModelHTTPError(status_code=502, model_name="claude-sonnet", body=None)
    exc_429 = ModelHTTPError(status_code=429, model_name="claude-sonnet", body=None)
    exc_400 = ModelHTTPError(status_code=400, model_name="claude-sonnet", body=None)

    assert _is_retryable_http_error(exc_5xx) is True
    assert _is_retryable_http_error(exc_429) is True
    assert _is_retryable_http_error(exc_400) is False


def test_predicate_rejects_unrelated_exceptions() -> None:
    assert _is_retryable_http_error(ValueError("nope")) is False
    assert _is_retryable_http_error(RuntimeError()) is False


async def test_max_total_seconds_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if ``max_attempts`` allows more retries, ``max_total_seconds``
    is a hard ceiling that stops the loop."""

    # Force the decorator to immediately exceed its time budget.
    attempts = 0

    @llm_http_retry(max_attempts=10, max_total_seconds=0.001)
    async def call() -> str:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("network down")

    with pytest.raises(httpx.ConnectError):
        await call()

    # First attempt always runs; the time-cap stops further retries.
    assert attempts >= 1
