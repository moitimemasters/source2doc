"""Tenacity-based retry decorators for external services (S3, Qdrant).

Both decorators only retry on transient (network/5xx) failures. They never retry
on 4xx (auth, missing-bucket, validation) — those are programming or
configuration errors that retrying cannot fix and only multiplies latency.

Backoff: exponential 0.5s -> 1s -> 2s -> 4s with +/-20% jitter, capped via
``max_total_seconds``. Default budget is 3 attempts / 60s for S3 and
3 attempts / 30s for Qdrant.

Example::

    from source2doc.resilience import s3_retry

    class MyS3:
        @s3_retry()
        async def upload(self, key: str, body: bytes) -> None:
            ...
"""

from __future__ import annotations

import collections.abc as cabc
import functools
import random
import typing as tp

import httpx
import redis.exceptions as redis_exc
import tenacity

from source2doc.logging import get_logger


logger = get_logger(__name__)


def _client_error_status_code(exc: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from a botocore ClientError."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None

    metadata = response.get("ResponseMetadata") or {}
    status = metadata.get("HTTPStatusCode")
    if isinstance(status, int):
        return status

    error_code = (response.get("Error") or {}).get("Code")
    if isinstance(error_code, str):
        # Botocore sometimes only sets Error.Code (e.g. "404", "500", or
        # name like "InternalError"). Try to parse a numeric form.
        try:
            return int(error_code)
        except ValueError:
            return None
    return None


def _is_s3_retryable(exc: BaseException) -> bool:
    """True if ``exc`` is a transient S3/network failure worth retrying."""
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True

    # botocore is an aioboto3 transitive dep; import lazily so this module
    # remains usable in test contexts that don't install aioboto3.
    try:
        from botocore import exceptions as botocore_exc
    except ImportError:
        botocore_exc = None  # type: ignore[assignment]

    if botocore_exc is not None:
        if isinstance(exc, botocore_exc.EndpointConnectionError):
            return True
        if isinstance(exc, botocore_exc.ConnectTimeoutError):
            return True
        if isinstance(exc, botocore_exc.ReadTimeoutError):
            return True
        if isinstance(exc, botocore_exc.ClientError):
            status = _client_error_status_code(exc)
            return bool(status is not None and 500 <= status < 600)

    return False


def _is_qdrant_retryable(exc: BaseException) -> bool:
    """True if ``exc`` is a transient Qdrant/network failure worth retrying."""
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True

    try:
        from qdrant_client.http import exceptions as qdrant_exc
    except ImportError:
        return False

    if isinstance(exc, qdrant_exc.UnexpectedResponse):
        status = getattr(exc, "status_code", None)
        return bool(isinstance(status, int) and 500 <= status < 600)

    return False


def _make_before_sleep(name: str) -> cabc.Callable[[tenacity.RetryCallState], None]:
    def _before_sleep(retry_state: tenacity.RetryCallState) -> None:
        attempt = retry_state.attempt_number
        outcome = retry_state.outcome
        exc = outcome.exception() if outcome is not None else None
        sleep_for = retry_state.next_action.sleep if retry_state.next_action else None
        logger.warning(
            "external_call_retry",
            target=name,
            attempt=attempt,
            sleep_seconds=sleep_for,
            last_exception_type=type(exc).__name__ if exc else None,
            last_exception=str(exc) if exc else None,
        )

    return _before_sleep


def _build_retrying(
    name: str,
    predicate: cabc.Callable[[BaseException], bool],
    max_attempts: int,
    max_total_seconds: float,
) -> tenacity.AsyncRetrying:
    return tenacity.AsyncRetrying(
        stop=tenacity.stop_any(
            tenacity.stop_after_attempt(max_attempts),
            tenacity.stop_after_delay(max_total_seconds),
        ),
        wait=tenacity.wait_exponential_jitter(
            initial=0.5,
            max=4.0,
            exp_base=2,
            jitter=0.1,  # ~20% peak-to-peak combined with the multiplier
        ),
        retry=tenacity.retry_if_exception(predicate),
        before_sleep=_make_before_sleep(name),
        reraise=True,
    )


def _retry_decorator(
    name: str,
    predicate: cabc.Callable[[BaseException], bool],
    max_attempts: int,
    max_total_seconds: float,
) -> cabc.Callable[[cabc.Callable[..., tp.Awaitable[tp.Any]]], cabc.Callable[..., tp.Any]]:
    """Internal builder used by ``s3_retry`` and ``qdrant_retry``."""

    def decorator(
        fn: cabc.Callable[..., tp.Awaitable[tp.Any]],
    ) -> cabc.Callable[..., tp.Any]:
        @functools.wraps(fn)
        async def wrapper(*args: tp.Any, **kwargs: tp.Any) -> tp.Any:
            # Allow per-call override via the ``self.resilience`` attr if set —
            # lets decorated methods on classes read fresh config from the
            # instance without re-decorating.
            instance_attempts = max_attempts
            instance_budget = max_total_seconds
            if args:
                instance = args[0]
                cfg = getattr(instance, "resilience", None)
                if cfg is not None:
                    instance_attempts = getattr(cfg, "max_attempts", max_attempts)
                    instance_budget = getattr(cfg, "max_total_seconds", max_total_seconds)

            retrying = _build_retrying(name, predicate, instance_attempts, instance_budget)
            async for attempt in retrying:
                with attempt:
                    return await fn(*args, **kwargs)
            # tenacity always reraises or returns; this is unreachable.
            raise RuntimeError("unreachable: tenacity exhausted without raising")

        return wrapper

    return decorator


def s3_retry(
    max_attempts: int = 3,
    max_total_seconds: float = 60.0,
) -> cabc.Callable[[cabc.Callable[..., tp.Awaitable[tp.Any]]], cabc.Callable[..., tp.Any]]:
    """Decorator that retries an async S3 call on transient/5xx errors.

    Retries on:
      * ``httpx.TransportError`` / ``httpx.TimeoutException``
      * ``botocore.exceptions.EndpointConnectionError``,
        ``ConnectTimeoutError``, ``ReadTimeoutError``
      * ``botocore.exceptions.ClientError`` with HTTP 5xx

    Does NOT retry 4xx (auth, validation, missing bucket).
    """
    return _retry_decorator(
        name="s3",
        predicate=_is_s3_retryable,
        max_attempts=max_attempts,
        max_total_seconds=max_total_seconds,
    )


def qdrant_retry(
    max_attempts: int = 3,
    max_total_seconds: float = 30.0,
) -> cabc.Callable[[cabc.Callable[..., tp.Awaitable[tp.Any]]], cabc.Callable[..., tp.Any]]:
    """Decorator that retries an async Qdrant call on transient/5xx errors.

    Retries on:
      * ``httpx.TransportError`` / ``httpx.TimeoutException``
      * ``qdrant_client.http.exceptions.UnexpectedResponse`` with HTTP 5xx
    """
    return _retry_decorator(
        name="qdrant",
        predicate=_is_qdrant_retryable,
        max_attempts=max_attempts,
        max_total_seconds=max_total_seconds,
    )


# ---------------------------------------------------------------------------
# Redis retry — guards individual XADD/XACK/EXPIRE calls against transient
# connection drops, timeouts, and BUSY-loading from a recovering primary.
# Server-side validation errors (``ResponseError``) intentionally do NOT
# retry — masking them would hide bugs.
# ---------------------------------------------------------------------------

_REDIS_RETRYABLE: tuple[type[BaseException], ...] = (
    redis_exc.ConnectionError,
    redis_exc.TimeoutError,
    redis_exc.BusyLoadingError,
)


def _is_redis_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _REDIS_RETRYABLE)


# Base backoff schedule (seconds): 0.2 -> 0.4 -> 0.8 -> 1.6 ..., doubling.
_REDIS_BASE_DELAY_S = 0.2
_REDIS_JITTER_FRACTION = 0.2  # +/- 20%


class _RedisExponentialJitterWait:
    """Tenacity wait strategy: 0.2s x 2^(n-1) with +/-20% uniform jitter."""

    def __init__(
        self,
        base: float = _REDIS_BASE_DELAY_S,
        jitter: float = _REDIS_JITTER_FRACTION,
    ) -> None:
        self.base = base
        self.jitter = jitter

    def __call__(self, retry_state: tenacity.RetryCallState) -> float:
        # attempt_number is 1-based; sleep happens after the failing attempt.
        n = max(retry_state.attempt_number, 1)
        target = self.base * (2 ** (n - 1))
        delta = target * self.jitter
        return max(0.0, target + random.uniform(-delta, delta))


def _make_redis_before_sleep(
    op_name: str,
) -> cabc.Callable[[tenacity.RetryCallState], None]:
    def _before_sleep(retry_state: tenacity.RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        next_delay = (
            retry_state.next_action.sleep if retry_state.next_action is not None else 0.0
        )
        logger.debug(
            "redis.retry",
            op=op_name,
            attempt=retry_state.attempt_number,
            last_exception_type=type(exc).__name__ if exc else None,
            next_delay_s=round(float(next_delay), 3),
        )

    return _before_sleep


def _make_redis_retry_error_callback(
    op_name: str,
) -> cabc.Callable[[tenacity.RetryCallState], tp.NoReturn]:
    def _on_final_failure(retry_state: tenacity.RetryCallState) -> tp.NoReturn:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "redis.retry_exhausted",
            op=op_name,
            attempts=retry_state.attempt_number,
            last_exception_type=type(exc).__name__ if exc else None,
        )
        if exc is not None:
            raise exc
        raise RuntimeError(f"redis_retry exhausted with no exception for {op_name}")

    return _on_final_failure


def redis_retry(
    max_attempts: int = 3,
    max_total_seconds: float = 10.0,
    _sleep: cabc.Callable[[float], cabc.Awaitable[None]] | None = None,
) -> cabc.Callable[[cabc.Callable], cabc.Callable]:
    """Decorate an async function with bounded retry on transient Redis errors.

    Retries on ``ConnectionError``, ``TimeoutError``, ``BusyLoadingError``.
    Backoff is exponential starting at 0.2s (0.2 -> 0.4 -> 0.8 ...) with +/-20%
    jitter and capped by ``max_total_seconds`` (whichever fires first).
    ``ResponseError`` and other server-side errors are not retried — they
    re-raise immediately.

    The decorated function must be a coroutine. Each retry logs at ``debug``
    with ``event="redis.retry"`` carrying ``attempt``, ``last_exception_type``,
    ``next_delay_s``. Final exhaustion logs at ``warning`` and re-raises the
    last underlying exception.

    ``_sleep`` is a test hook — pass an async no-op to skip real sleeps.
    """

    def decorator(fn: cabc.Callable) -> cabc.Callable:
        op_name = getattr(fn, "__qualname__", getattr(fn, "__name__", "redis_op"))

        @functools.wraps(fn)
        async def wrapper(*args: tp.Any, **kwargs: tp.Any) -> tp.Any:
            retrying_kwargs: dict[str, tp.Any] = {
                "stop": tenacity.stop_any(
                    tenacity.stop_after_attempt(max_attempts),
                    tenacity.stop_after_delay(max_total_seconds),
                ),
                "wait": _RedisExponentialJitterWait(),
                "retry": tenacity.retry_if_exception(_is_redis_retryable),
                "before_sleep": _make_redis_before_sleep(op_name),
                "retry_error_callback": _make_redis_retry_error_callback(op_name),
                "reraise": False,
            }
            if _sleep is not None:
                retrying_kwargs["sleep"] = _sleep
            retrying = tenacity.AsyncRetrying(**retrying_kwargs)
            async for attempt in retrying:
                with attempt:
                    return await fn(*args, **kwargs)
            # Unreachable: retry_error_callback always raises on exhaustion.
            raise RuntimeError("redis_retry: unreachable")

        return wrapper

    return decorator
