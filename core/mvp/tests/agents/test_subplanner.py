"""Smoke test for the subplanner agent via pydantic-ai TestModel.

Verifies the agent's output schema (``SubplanOutput``) is wired correctly
and that the runner returns structured output without hitting a real LLM.
"""

from __future__ import annotations

from pathlib import Path

import pydantic_ai
from pydantic_ai.models.test import TestModel

from source2doc.agents.config import BaseAgentConfig
from source2doc.agents.runner import run_agent

from docgen_core.agents.subplanner import SubplanOutput


def _agent_config() -> BaseAgentConfig:
    return BaseAgentConfig(
        instructions="test",
        max_attempts=2,
        timeout_seconds=10,
        response_tokens_limit=100,
    )


async def test_subplanner_returns_structured_output() -> None:
    agent: pydantic_ai.Agent = pydantic_ai.Agent(
        model=TestModel(),
        output_type=SubplanOutput,
        instructions="subplanner",
    )

    result = await run_agent(
        agent,
        "section_id: client\ntitle: Client\nscope_paths:\n  - httpx/_client.py",
        deps=None,
        agent_name="subplanner",
        config=_agent_config(),
    )
    out = result.output

    assert isinstance(out, SubplanOutput)
    assert isinstance(out.section_id, str)
    assert isinstance(out.page_specs, list)


def test_subplanner_prompt_loadable() -> None:
    """The shipped subplanner.yaml must parse via the existing prompt loader."""
    from docgen_core.config.loader import load_prompt

    here = Path(__file__).resolve().parents[2] / "configs" / "agents" / "subplanner.yaml"
    cfg = load_prompt(here)
    assert cfg.instructions
