"""Block-restructure agent.

The agent reformats an already-drafted ``DocPage`` so its blocks reflect
the schema cleanly: literal markdown headings get promoted to
``HeadingBlock``, runaway prose is split into sections, and clearly
mis-typed blocks are corrected. The agent is **stateless** — it has no
RAG tools, runs in one round-trip, and is bound to ``temperature=0.1``
inside the prompt to discourage rewrites that change meaning.
"""

from pathlib import Path

import pydantic_ai

from source2doc import DocPage
from source2doc.config import LLMConfig

from docgen_core.agents.deps import DocGenDeps
from docgen_core.agents.language_directive import build_directive
from docgen_core.config.agents import AgentConfig
from docgen_core.config.loader import load_prompt
from docgen_core.services.llm import create_llm_model


def create_normalizer_agent(
    llm_config: LLMConfig,
    prompt_path: Path,
    output_language: str = "en",
) -> tuple[pydantic_ai.Agent[DocGenDeps, DocPage], AgentConfig]:
    prompt_config = load_prompt(prompt_path)
    model = create_llm_model(llm_config)

    instructions = prompt_config.instructions + build_directive(output_language, "normalizer")
    agent = pydantic_ai.Agent(
        model=model,
        deps_type=DocGenDeps,
        output_type=DocPage,
        instructions=instructions,
        retries=prompt_config.max_result_retries,
    )

    return agent, prompt_config
