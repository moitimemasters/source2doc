"""Tenacity-based retry helpers for LLM HTTP calls.

Two flavours of retry exist in this codebase already:

* The agent-level retry in ``source2doc/agents/runner.py`` covers
  ``UnexpectedModelBehavior`` and OpenAI-SDK exceptions because those
  bubble up *after* the HTTP layer. ``UsageLimitExceeded`` is excluded
  on purpose — it's a deliberate cap, not a transient fault.
* This module covers the *transport* layer — connection drops, read
  timeouts, 5xx, 429 — and is provider-agnostic so it can wrap an
  ``await agent.run(...)`` regardless of whether the model is OpenAI,
  Anthropic or anything else Pydantic-AI exposes.

The two layers are complementary and intentionally not merged:
agent-level retries can rebuild the conversation state on failure;
HTTP-level retries are stateless and should run *first*.

Backoff is exponential with ±20% jitter — 1s → 2s → 4s by default —
capped by ``max_total_seconds`` so a misbehaving upstream cannot keep
us spinning indefinitely.
"""

from __future__ import annotations

import collections.abc as cabc
import typing as tp

import httpx
import tenacity

from source2doc.logging import get_logger


logger = get_logger(__name__)


# Type alias for the wrapped async function. Using ``tp.Any`` for the
# return type because we wrap heterogeneous Pydantic-AI return shapes.
F = tp.TypeVar("F", bound=cabc.Callable[..., cabc.Awaitable[tp.Any]])


def _is_retryable_http_error(exc: BaseException) -> bool:
    """Predicate for tenacity ``retry_if_exception``.

    Retries:
    * ``httpx.TransportError`` — connection-level failures (DNS, refused, reset).
    * ``httpx.TimeoutException`` — read/write/pool timeouts.
    * ``httpx.HTTPStatusError`` with status 5xx or exactly 429.
    * Pydantic-AI's ``ModelHTTPError`` (which wraps the same status codes
      from the provider SDKs).

    Does NOT retry on 4xx other than 429 — those are caller bugs and
    will only burn budget if retried.
    """

    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or 500 <= status < 600

    # Pydantic-AI wraps SDK HTTP errors. Import is lazy because this
    # module sits in source2doc-shared and we don't want the import cost
    # on cold paths that don't touch the LLM at all.
    try:
        from pydantic_ai.exceptions import ModelHTTPError  # noqa: PLC0415
    except ImportError:
        return False

    if isinstance(exc, ModelHTTPError):
        status = getattr(exc, "status_code", 0)
        return status == 429 or 500 <= status < 600

    return False


_RATE_LIMIT_BACKOFF_SECONDS = 10.0


def _is_rate_limit_error(exc: BaseException | None) -> bool:
    """True iff the exception is HTTP 429 (rate limit / inflight cap).

    Provider-agnostic: handles raw httpx, pydantic-ai's ModelHTTPError,
    and the generic ``status_code`` attribute that openai / anthropic
    SDK errors expose. Anything else (5xx, transport timeouts, etc.)
    falls through to the regular exponential backoff.
    """
    if exc is None:
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status == 429:
        return True
    # Pydantic-AI wraps provider HTTP errors; lazy import.
    try:
        from pydantic_ai.exceptions import ModelHTTPError  # noqa: PLC0415
    except ImportError:
        return False
    if isinstance(exc, ModelHTTPError):
        return getattr(exc, "status_code", 0) == 429
    return False


def _make_wait() -> cabc.Callable[[tenacity.RetryCallState], float]:
    """1s → 2s → 4s → 8s exponential backoff with built-in jitter, except
    for HTTP 429 which always waits a flat ``_RATE_LIMIT_BACKOFF_SECONDS``.

    Eliza-class providers reset their per-key inflight counter on a
    coarse window — bursting at sub-second backoff just hits 429 again
    without giving the upstream room to drain. A flat 10 s wait gives
    in-flight calls time to complete and the inflight counter to clear.
    Other retriable errors (5xx, transport timeouts) keep the standard
    exponential ramp because they're typically transient and don't
    benefit from a long wait.
    """

    base = tenacity.wait_exponential_jitter(
        initial=1.0, max=8.0, exp_base=2.0, jitter=1.0
    )

    def _wait(retry_state: tenacity.RetryCallState) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if _is_rate_limit_error(exc):
            return _RATE_LIMIT_BACKOFF_SECONDS
        return base(retry_state)

    return _wait


def llm_http_retry(
    max_attempts: int = 3,
    max_total_seconds: float = 120.0,
) -> cabc.Callable[[F], F]:
    """Decorator that retries an async function on transient LLM HTTP errors.

    Args:
        max_attempts: Total number of attempts including the first.
            ``3`` means one initial call + two retries.
        max_total_seconds: Hard wall-clock cap across all attempts.
            When this is hit tenacity stops retrying and re-raises the
            most recent exception, even if attempts remain.
    """

    def decorator(fn: F) -> F:
        async def _before_sleep(retry_state: tenacity.RetryCallState) -> None:
            exc = retry_state.outcome.exception() if retry_state.outcome else None
            logger.warning(
                "llm_http_retry",
                attempt=retry_state.attempt_number,
                error=str(exc) if exc else None,
                error_type=type(exc).__name__ if exc else None,
            )

        @tenacity.retry(
            stop=(
                tenacity.stop_after_attempt(max_attempts)
                | tenacity.stop_after_delay(max_total_seconds)
            ),
            wait=_make_wait(),
            retry=tenacity.retry_if_exception(_is_retryable_http_error),
            before_sleep=_before_sleep,
            reraise=True,
        )
        async def wrapper(*args: tp.Any, **kwargs: tp.Any) -> tp.Any:
            return await fn(*args, **kwargs)

        return tp.cast(F, wrapper)

    return decorator


__all__ = ["llm_http_retry", "_is_retryable_http_error"]
