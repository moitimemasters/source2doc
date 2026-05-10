"""Tests covering the agent_runs persistence path baked into ``run_agent``.

When the caller passes ``storage=...`` plus the ``generation_id`` /
``page_id`` / ``section_id`` / ``attempt`` kwargs, every Pydantic-AI
``agent.run()`` invocation must INSERT one ``agent_runs`` row, regardless
of whether the run succeeded, raised a transient error, or hit the hard
timeout. Previously the runner had no DB awareness — these tests pin the
new contract so a refactor doesn't silently lose the conversation log.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from source2doc.agents.config import BaseAgentConfig
from source2doc.agents.runner import run_agent


GEN_ID = "11111111-2222-3333-4444-555555555555"


def _agent_config(**overrides: object) -> BaseAgentConfig:
    return BaseAgentConfig(
        instructions="t",
        max_attempts=overrides.pop("max_attempts", 1),  # type: ignore[arg-type]
        timeout_seconds=overrides.pop("timeout_seconds", 5),  # type: ignore[arg-type]
        response_tokens_limit=200,
        request_limit=overrides.pop("request_limit", 5),  # type: ignore[arg-type]
        **overrides,  # type: ignore[arg-type]
    )


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int, requests: int = 1) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.requests = requests


class _RunResult:
    def __init__(
        self,
        *,
        output: object,
        usage: _Usage | None = None,
        model: str | None = None,
    ) -> None:
        self.output = output
        self._usage = usage or _Usage(10, 5)
        self.model = model

    def usage(self) -> _Usage:
        return self._usage


def _fake_agent(*, side_effect: object = None, result: _RunResult | None = None) -> object:
    """Pydantic-AI Agent stub: only ``run`` and ``model`` are touched."""
    agent = SimpleNamespace()
    agent.model = SimpleNamespace(model_name="test-model")

    async def _run(*args, **kwargs):  # noqa: ARG001 — args ignored
        if side_effect is not None:
            raise side_effect  # type: ignore[misc]
        return result

    agent.run = _run
    return agent


@pytest.mark.asyncio
async def test_run_agent_records_success_row() -> None:
    storage = SimpleNamespace(record_agent_run=AsyncMock(return_value=1))
    fake_output = SimpleNamespace(model_dump=lambda mode="json": {"title": "Intro"})  # noqa: ARG005
    result = _RunResult(output=fake_output, usage=_Usage(120, 80, requests=2), model="gpt-4o")

    out = await run_agent(
        _fake_agent(result=result),  # type: ignore[arg-type]
        "go",
        deps=None,
        agent_name="writer",
        config=_agent_config(),
        storage=storage,
        generation_id=GEN_ID,
        page_id="intro",
        attempt=1,
    )
    assert out is result
    storage.record_agent_run.assert_awaited_once()
    kwargs = storage.record_agent_run.await_args.kwargs
    assert kwargs["generation_id"] == UUID(GEN_ID)
    assert kwargs["agent_name"] == "writer"
    assert kwargs["page_id"] == "intro"
    assert kwargs["section_id"] is None
    assert kwargs["attempt"] == 1
    assert kwargs["success"] is True
    assert kwargs["error_type"] is None
    assert kwargs["input_tokens"] == 120
    assert kwargs["output_tokens"] == 80
    assert kwargs["total_tokens"] == 200
    assert kwargs["request_count"] == 2
    # Output is the dumped pydantic-style payload, not the SimpleNamespace.
    assert kwargs["output"] == {"title": "Intro"}
    # Messages list comes from ``capture_run_messages``; the stub agent
    # never opens that context, so the list is empty — that's still a
    # valid persistence row (the runner records what it has).
    assert isinstance(kwargs["messages"], list)


@pytest.mark.asyncio
async def test_run_agent_records_failure_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """A persistent error must still INSERT one agent_runs row with
    ``success=False`` and the error metadata before re-raising."""

    import tenacity

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

    storage = SimpleNamespace(record_agent_run=AsyncMock(return_value=2))
    boom = ValueError("schema mismatch")  # not retryable

    with pytest.raises(ValueError, match="schema mismatch"):
        await run_agent(
            _fake_agent(side_effect=boom),  # type: ignore[arg-type]
            "go",
            deps=None,
            agent_name="critic",
            config=_agent_config(max_attempts=1),
            storage=storage,
            generation_id=GEN_ID,
            page_id="page-1",
            attempt=2,
        )

    storage.record_agent_run.assert_awaited_once()
    kwargs = storage.record_agent_run.await_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["error_type"] == "ValueError"
    assert kwargs["error_message"] == "schema mismatch"
    # No usage available on a failed run -> tokens recorded as None
    assert kwargs["input_tokens"] is None
    assert kwargs["output_tokens"] is None
    assert kwargs["output"] is None
    assert kwargs["attempt"] == 2


@pytest.mark.asyncio
async def test_run_agent_records_timeout_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The terminal LLMTimeoutError branch also persists a failure row."""

    import tenacity

    from source2doc.errors import LLMTimeoutError

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

    storage = SimpleNamespace(record_agent_run=AsyncMock(return_value=3))

    class _SlowAgent:
        model = SimpleNamespace(model_name="slow")

        async def run(self, *args, **kwargs):  # noqa: ARG002
            await asyncio.sleep(2)

    with pytest.raises(LLMTimeoutError):
        await run_agent(
            _SlowAgent(),  # type: ignore[arg-type]
            "go",
            deps=None,
            agent_name="planner",
            config=_agent_config(max_attempts=1, timeout_seconds=1),
            storage=storage,
            generation_id=GEN_ID,
        )

    storage.record_agent_run.assert_awaited_once()
    kwargs = storage.record_agent_run.await_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["error_type"] == "LLMTimeoutError"


@pytest.mark.asyncio
async def test_run_agent_skips_persistence_without_storage() -> None:
    """No storage kwarg => zero DB writes (preserves CLI / standalone flows)."""
    result = _RunResult(output={"x": 1})

    out = await run_agent(
        _fake_agent(result=result),  # type: ignore[arg-type]
        "go",
        deps=None,
        agent_name="planner",
        config=_agent_config(),
    )
    assert out is result  # sanity: behaviour unchanged when storage missing


@pytest.mark.asyncio
async def test_run_agent_swallows_persistence_exceptions() -> None:
    """A DB outage in record_agent_run must not crash the agent run."""
    storage = SimpleNamespace(
        record_agent_run=AsyncMock(side_effect=RuntimeError("db down")),
    )
    result = _RunResult(output={"ok": True})

    out = await run_agent(
        _fake_agent(result=result),  # type: ignore[arg-type]
        "go",
        deps=None,
        agent_name="planner",
        config=_agent_config(),
        storage=storage,
        generation_id=GEN_ID,
    )
    assert out is result
    storage.record_agent_run.assert_awaited_once()
