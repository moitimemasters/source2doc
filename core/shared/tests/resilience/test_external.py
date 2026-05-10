import pytest
import redis.exceptions as redis_exc

from source2doc.resilience.external import redis_retry


async def _no_sleep(_s):
    return None


async def test_redis_retry_retries_then_reraises_on_connection_error():
    """3 attempts then re-raises the last ConnectionError."""
    call_count = 0

    @redis_retry(max_attempts=3, max_total_seconds=10.0, _sleep=_no_sleep)
    async def always_fails():
        nonlocal call_count
        call_count += 1
        raise redis_exc.ConnectionError("nope")

    with pytest.raises(redis_exc.ConnectionError):
        await always_fails()

    assert call_count == 3


async def test_redis_retry_returns_on_eventual_success():
    """Transient TimeoutError -> success on attempt 2."""
    call_count = 0

    @redis_retry(max_attempts=3, max_total_seconds=10.0, _sleep=_no_sleep)
    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise redis_exc.TimeoutError("blip")
        return "ok"

    result = await flaky()
    assert result == "ok"
    assert call_count == 2


async def test_redis_retry_does_not_retry_response_error():
    """ResponseError is not transient — surface immediately, no retry."""
    call_count = 0

    @redis_retry(max_attempts=3, max_total_seconds=10.0, _sleep=_no_sleep)
    async def bad_command():
        nonlocal call_count
        call_count += 1
        raise redis_exc.ResponseError("WRONGTYPE")

    with pytest.raises(redis_exc.ResponseError):
        await bad_command()

    assert call_count == 1


async def test_redis_retry_does_not_retry_value_error():
    """Non-redis exceptions are not retried."""
    call_count = 0

    @redis_retry(max_attempts=3, max_total_seconds=10.0, _sleep=_no_sleep)
    async def boom():
        nonlocal call_count
        call_count += 1
        raise ValueError("logic")

    with pytest.raises(ValueError):
        await boom()

    assert call_count == 1


async def test_redis_retry_passes_args_and_kwargs():
    @redis_retry(max_attempts=2, max_total_seconds=1.0, _sleep=_no_sleep)
    async def echo(a, b, *, c):
        return (a, b, c)

    assert await echo(1, 2, c=3) == (1, 2, 3)


async def test_redis_retry_retries_busy_loading_error():
    call_count = 0

    @redis_retry(max_attempts=3, max_total_seconds=10.0, _sleep=_no_sleep)
    async def loading():
        nonlocal call_count
        call_count += 1
        raise redis_exc.BusyLoadingError("LOADING")

    with pytest.raises(redis_exc.BusyLoadingError):
        await loading()

    assert call_count == 3
