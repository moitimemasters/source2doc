"""Tests for ``docgen_core.workers.metrics`` (B3.1).

The handler-side helper must:
* extract usage from a Pydantic-AI run result;
* compute cost when pricing is supplied (and skip silently otherwise);
* never crash a generation if storage / usage / pricing fail.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from docgen_core.workers import metrics as metrics_mod


GENERATION_ID = "11111111-2222-3333-4444-555555555555"


class _RunResult:
    """Stand-in for an ``AgentRunResult``: exposes ``.usage()`` + ``.model``."""

    def __init__(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str | None = None,
        raise_on_usage: bool = False,
    ) -> None:
        self._usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
        self.model = model
        self._raise_on_usage = raise_on_usage

    def usage(self) -> object:
        if self._raise_on_usage:
            raise RuntimeError("usage call exploded")
        return self._usage


def _make_run_result(**kwargs: object) -> _RunResult:
    return _RunResult(**kwargs)  # type: ignore[arg-type]


def _make_env(
    *,
    storage: object | None,
    pricing: dict | None = None,
    llm_model: str = "gpt-4o",
) -> object:
    return SimpleNamespace(
        storage=storage,
        pricing=pricing or {},
        config=SimpleNamespace(llm=SimpleNamespace(model=llm_model)),
    )


@pytest.mark.asyncio
async def test_record_agent_metric_persists_with_cost() -> None:
    storage = SimpleNamespace(record_metric=AsyncMock())
    from worker.config import ModelPricing

    pricing = {"gpt-4o": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00)}
    env = _make_env(storage=storage, pricing=pricing, llm_model="gpt-4o")

    run_result = _make_run_result(input_tokens=1000, output_tokens=500, model="gpt-4o")

    await metrics_mod.record_agent_metric(env, GENERATION_ID, "plan", run_result)

    storage.record_metric.assert_awaited_once()
    kwargs = storage.record_metric.await_args.kwargs
    assert kwargs["generation_id"] == UUID(GENERATION_ID)
    assert kwargs["step"] == "plan"
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["prompt_tokens"] == 1000
    assert kwargs["completion_tokens"] == 500
    assert kwargs["cost_usd"] == pytest.approx(0.0025 + 0.005)


@pytest.mark.asyncio
async def test_record_agent_metric_records_null_cost_when_unpriced() -> None:
    storage = SimpleNamespace(record_metric=AsyncMock())
    env = _make_env(storage=storage, pricing={}, llm_model="custom-llm")

    run_result = _make_run_result(input_tokens=10, output_tokens=5, model="custom-llm")

    await metrics_mod.record_agent_metric(env, GENERATION_ID, "write", run_result)

    storage.record_metric.assert_awaited_once()
    assert storage.record_metric.await_args.kwargs["cost_usd"] is None


@pytest.mark.asyncio
async def test_record_agent_metric_skips_when_no_storage() -> None:
    """A stub env without storage must not raise — handlers shouldn't care."""
    env = _make_env(storage=None)
    run_result = _make_run_result(input_tokens=1, output_tokens=1)
    # Just exercise the path; no assertion needed beyond "doesn't raise".
    await metrics_mod.record_agent_metric(env, GENERATION_ID, "plan", run_result)


@pytest.mark.asyncio
async def test_record_agent_metric_swallows_usage_errors() -> None:
    """A pydantic-ai SDK quirk that throws from .usage() must not crash."""
    storage = SimpleNamespace(record_metric=AsyncMock())
    env = _make_env(storage=storage)
    run_result = _make_run_result(input_tokens=1, output_tokens=1, raise_on_usage=True)

    await metrics_mod.record_agent_metric(env, GENERATION_ID, "review", run_result)

    storage.record_metric.assert_not_called()


@pytest.mark.asyncio
async def test_record_agent_metric_swallows_storage_errors() -> None:
    """Persistence failures get logged at debug, never re-raised."""
    storage = SimpleNamespace(record_metric=AsyncMock(side_effect=RuntimeError("db down")))
    env = _make_env(storage=storage)
    run_result = _make_run_result(input_tokens=1, output_tokens=1, model="gpt-4o")

    await metrics_mod.record_agent_metric(env, GENERATION_ID, "review", run_result)
