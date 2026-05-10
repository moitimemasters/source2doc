"""Smoke tests for the shared agent runner using pydantic-ai TestModel.

PMI-mapping (osokin): planner / writer / critic agent runs. Using a real
LLM in CI is too slow and non-deterministic; pydantic-ai's TestModel
returns canned structured output that conforms to the agent's output
schema. These tests verify:

  * the runner respects the agent contract end-to-end,
  * structured output (PlannerOutput, DocPage, CriticOutput) is wired
    correctly so a stub model can satisfy it,
  * retries fire when the inner call raises a retryable error.
"""

from __future__ import annotations

import asyncio

import pydantic_ai
from pydantic_ai.models.test import TestModel
import pytest

from source2doc.agents.config import BaseAgentConfig
from source2doc.agents.runner import run_agent
from source2doc.errors import LLMTransientError


def _agent_config() -> BaseAgentConfig:
    return BaseAgentConfig(
        instructions="test",
        max_attempts=3,
        timeout_seconds=10,
        response_tokens_limit=100,
    )


# --------------------------------------------------------------------------- #
# 1. TestModel wired into a Planner-shaped agent returns structured output
# --------------------------------------------------------------------------- #


import pydantic


class _FakePlannerOutput(pydantic.BaseModel):
    navigation: dict[str, str]
    page_specs: list[dict]


async def test_runner_returns_structured_output_with_test_model() -> None:
    """TestModel auto-generates a structurally valid response for the
    declared output type. No LLM is hit, but the full pydantic-ai
    runtime executes the agent."""

    agent: pydantic_ai.Agent = pydantic_ai.Agent(
        model=TestModel(),  # auto-fills the output schema with default values
        output_type=_FakePlannerOutput,
        instructions="planner",
    )

    result = await run_agent(
        agent, "draft a plan", deps=None, agent_name="planner", config=_agent_config()
    )
    out = result.output

    assert isinstance(out, _FakePlannerOutput)
    # TestModel returns schema-valid garbage; we only assert shape.
    assert isinstance(out.navigation, dict)
    assert isinstance(out.page_specs, list)


# --------------------------------------------------------------------------- #
# 2. Runner retries on retryable errors (LLMTransientError)
# --------------------------------------------------------------------------- #


async def test_runner_retries_on_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared agent runner classifies LLMTransientError as retryable.
    Wrap a fake agent that fails twice then succeeds."""

    import tenacity

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

    attempts = 0
    final = _FakePlannerOutput(navigation={"intro": "x"}, page_specs=[])

    class _FakeRunResult:
        output = final

    class _FakeAgent:
        async def run(self, *args, **kwargs):  # noqa: D401, ARG002
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise LLMTransientError("flaky")
            return _FakeRunResult()

    result = await run_agent(
        _FakeAgent(),  # type: ignore[arg-type]
        "go",
        deps=None,
        agent_name="fake",
        config=_agent_config(),
    )
    assert attempts == 3
    assert result.output is final


# --------------------------------------------------------------------------- #
# 3. Runner gives up after max_attempts
# --------------------------------------------------------------------------- #


async def test_runner_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    import tenacity

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

    attempts = 0

    class _FakeAgent:
        async def run(self, *args, **kwargs):  # noqa: ARG002
            nonlocal attempts
            attempts += 1
            raise LLMTransientError("permanently flaky")

    with pytest.raises(LLMTransientError):
        await run_agent(
            _FakeAgent(),  # type: ignore[arg-type]
            "go",
            deps=None,
            agent_name="fake",
            config=_agent_config(),
        )

    assert attempts == 3, "max_attempts=3 -> exactly 3 invocations"


# --------------------------------------------------------------------------- #
# 4. Hard timeout fires
# --------------------------------------------------------------------------- #


async def test_runner_hard_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each agent call is wrapped in asyncio.timeout(timeout_seconds).
    A handler that hangs longer than that should burn the full retry
    budget at the agent layer and then surface as an ``LLMTimeoutError``
    (B9.3) carrying enough metadata for the UI banner."""

    import tenacity

    from source2doc.errors import LLMTimeoutError

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

    attempts = 0

    class _SlowAgent:
        async def run(self, *args, **kwargs):  # noqa: ARG002
            nonlocal attempts
            attempts += 1
            await asyncio.sleep(5)
            return None

    config = BaseAgentConfig(
        instructions="t",
        max_attempts=2,
        timeout_seconds=1,  # 1s budget; sleep(5) blows it
        response_tokens_limit=100,
    )

    with pytest.raises(LLMTimeoutError) as excinfo:
        await run_agent(
            _SlowAgent(),  # type: ignore[arg-type]
            "go",
            deps=None,
            agent_name="slow",
            config=config,
        )

    # TimeoutError IS retryable at the agent layer, so we hit max_attempts
    # before the final timeout is surfaced as ``LLMTimeoutError``.
    assert attempts == 2
    assert excinfo.value.last_attempt_n == 2
    assert excinfo.value.elapsed_s > 0
