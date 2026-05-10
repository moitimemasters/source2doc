from pathlib import Path

import pydantic_ai

from source2doc import DocPage
from source2doc.agents.history import truncate_old_tool_results
from source2doc.config import LLMConfig

from docgen_core.agents.deps import DocGenDeps
from docgen_core.agents.language_directive import build_directive
from docgen_core.config.agents import AgentConfig
from docgen_core.config.loader import load_prompt
from docgen_core.services.llm import create_llm_model
from docgen_core.tools.files import read_file
from docgen_core.tools.search import search_code


def create_writer_agent(
    llm_config: LLMConfig,
    prompt_path: Path,
    output_language: str = "en",
) -> tuple[pydantic_ai.Agent[DocGenDeps, DocPage], AgentConfig]:
    prompt_config = load_prompt(prompt_path)
    model = create_llm_model(llm_config)

    instructions = prompt_config.instructions + build_directive(output_language, "writer")
    agent = pydantic_ai.Agent(
        model=model,
        deps_type=DocGenDeps,
        output_type=DocPage,
        instructions=instructions,
        retries=prompt_config.max_result_retries,
        history_processors=[truncate_old_tool_results],
    )

    search_code_retries = prompt_config.tool_retries.get("search_code", 3)
    read_file_retries = prompt_config.tool_retries.get("read_file", 2)
    agent.tool(retries=search_code_retries)(search_code)
    agent.tool(retries=read_file_retries)(read_file)
    return agent, prompt_config
