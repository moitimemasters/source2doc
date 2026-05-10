"""B9.3 — verify that an ``LLMTimeoutError`` raised by an inner handler
results in a ``step.failed`` event with ``reason='llm_timeout'`` and the
expected metadata fields. The UI's timeout banner depends on this exact
shape (see ``StreamDetailContainer.findLlmTimeout``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from source2doc.errors import LLMTimeoutError

from docgen_core.workers.context import GenerationContext
from docgen_core.workers.resilience import resilient_handler


GENERATION_ID = "11111111-2222-3333-4444-555555555555"


def _make_env() -> SimpleNamespace:
    return SimpleNamespace(event_bus=SimpleNamespace(emit=AsyncMock(return_value=None)))


def _make_ctx() -> GenerationContext:
    return GenerationContext(generation_id=GENERATION_ID)


async def test_llm_timeout_emits_reason_field() -> None:
    """``LLMTimeoutError`` is treated as terminal — emit once, no retries."""

    env = _make_env()
    attempts = 0

    @resilient_handler(step_name="writer_step", max_attempts=3)
    async def handler(_env, _ctx, _data):
        nonlocal attempts
        attempts += 1
        raise LLMTimeoutError(
            model="claude-sonnet-4-6",
            elapsed_s=42.5,
            last_attempt_n=3,
        )

    with pytest.raises(LLMTimeoutError):
        await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})

    # Terminal: must NOT retry — burning budget on an already-exhausted
    # HTTP retry is wasteful.
    assert attempts == 1

    # Single ``step.failed`` event with the structured reason.
    assert env.event_bus.emit.await_count == 1
    args = env.event_bus.emit.await_args
    assert args.args[0] == "step.failed"
    payload = args.args[1]

    assert payload["step_name"] == "writer_step"
    assert payload["error_type"] == "LLMTimeoutError"
    assert payload["reason"] == "llm_timeout"
    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["elapsed_s"] == 42.5
    assert payload["last_attempt_n"] == 3
    assert payload["retry_after"] is None
    # Human-readable message — the UI uses this in the banner subline.
    assert "timed out" in payload["error_message"].lower()
    assert "3 attempt" in payload["error_message"]


async def test_non_timeout_failure_has_no_reason_field() -> None:
    """Generic errors should keep their existing payload shape — adding
    a ``reason`` field by accident would break the UI's selector logic."""

    env = _make_env()

    @resilient_handler(step_name="planner_step", max_attempts=1)
    async def handler(_env, _ctx, _data):
        raise ValueError("not a timeout")

    with pytest.raises(ValueError):
        await handler(env, _make_ctx(), {"generation_id": GENERATION_ID})

    args = env.event_bus.emit.await_args
    payload = args.args[1]
    assert "reason" not in payload
    assert payload["error_type"] == "ValueError"
