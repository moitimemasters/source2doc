"""Resilient handler decorator tests.

PMI-mapping (osokin): pipeline reliability — every handler is wrapped in
``resilient_handler``. On a transient error the inner function is retried
``max_attempts`` times; on a final failure a ``step.failed`` event is
emitted with ``is_transient`` set correctly so the UI can distinguish
recoverable vs. permanent issues.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import openai
import pytest

from source2doc.errors import LLMTransientError

from docgen_core.workers.context import GenerationContext
from docgen_core.workers.resilience import resilient_handler


GENERATION_ID = "11111111-2222-3333-4444-555555555555"


def _make_env() -> SimpleNamespace:
    """Duck-typed DocGenEnv stub. resilient_handler only touches event_bus."""
    return SimpleNamespace(event_bus=SimpleNamespace(emit=AsyncMock(return_value=None)))


def _make_ctx() -> GenerationContext:
    return GenerationContext(generation_id=GENERATION_ID)


async def test_handler_runs_once_on_success() -> None:
    env = _make_env()
    calls = 0

    @resilient_handler(step_name="my_step", max_attempts=3)
    async def handler(_env, _ctx, _data):
        nonlocal calls
        calls += 1

    await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})
    assert calls == 1
    env.event_bus.emit.assert_not_awaited()


async def test_transient_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLMTransientError is in the retryable set — handler should be
    invoked up to max_attempts before giving up."""

    # Patch tenacity sleep to fast-forward.
    import tenacity

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

    env = _make_env()
    attempts = 0

    @resilient_handler(step_name="flaky_step", max_attempts=3)
    async def handler(_env, _ctx, _data):
        nonlocal attempts
        attempts += 1
        raise LLMTransientError("temporary glitch")

    with pytest.raises(LLMTransientError):
        await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})

    assert attempts == 3, "handler must be retried up to max_attempts"

    # step.failed emitted exactly once with is_transient=True.
    assert env.event_bus.emit.await_count == 1
    args = env.event_bus.emit.await_args
    assert args.args[0] == "step.failed"
    payload = args.args[1]
    assert payload["step_name"] == "flaky_step"
    assert payload["error_type"] == "LLMTransientError"
    assert payload["is_transient"] is True


async def test_non_retryable_error_fails_immediately() -> None:
    env = _make_env()
    attempts = 0

    @resilient_handler(step_name="boom_step", max_attempts=3)
    async def handler(_env, _ctx, _data):
        nonlocal attempts
        attempts += 1
        raise ValueError("permanent problem")

    with pytest.raises(ValueError):
        await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})

    assert attempts == 1, "non-retryable errors must not retry"

    args = env.event_bus.emit.await_args
    payload = args.args[1]
    assert payload["is_transient"] is False
    assert payload["error_type"] == "ValueError"


async def test_openai_5xx_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    import tenacity

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

    env = _make_env()
    attempts = 0

    @resilient_handler(step_name="llm_step", max_attempts=2)
    async def handler(_env, _ctx, _data):
        nonlocal attempts
        attempts += 1
        # OpenAI 503 should be classified as retryable.
        raise openai.APIStatusError(
            "service unavailable",
            response=SimpleNamespace(status_code=503, request=None, headers={}),  # type: ignore[arg-type]
            body=None,
        )

    with pytest.raises(openai.APIStatusError):
        await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})

    assert attempts == 2


async def test_openai_4xx_is_not_retryable() -> None:
    env = _make_env()
    attempts = 0

    @resilient_handler(step_name="llm_step", max_attempts=3)
    async def handler(_env, _ctx, _data):
        nonlocal attempts
        attempts += 1
        raise openai.APIStatusError(
            "bad request",
            response=SimpleNamespace(status_code=400, request=None, headers={}),  # type: ignore[arg-type]
            body=None,
        )

    with pytest.raises(openai.APIStatusError):
        await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})

    assert attempts == 1


async def test_step_failed_emit_does_not_mask_original_error() -> None:
    """If the event_bus itself blows up while emitting step.failed,
    the original handler exception must still propagate."""

    env = SimpleNamespace(event_bus=SimpleNamespace(emit=AsyncMock(side_effect=RuntimeError("bus down"))))
    attempts = 0

    @resilient_handler(step_name="combo_step", max_attempts=1)
    async def handler(_env, _ctx, _data):
        nonlocal attempts
        attempts += 1
        raise ValueError("real reason")

    with pytest.raises(ValueError, match="real reason"):
        await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})

    assert attempts == 1
