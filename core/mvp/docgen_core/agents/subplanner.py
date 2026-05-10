from pathlib import Path

import pydantic
import pydantic_ai

from source2doc.agents.history import truncate_old_tool_results
from source2doc.config import LLMConfig

from docgen_core.agents.deps import DocGenDeps
from docgen_core.agents.language_directive import build_directive
from docgen_core.agents.planner import PageSpec
from docgen_core.config.agents import AgentConfig
from docgen_core.config.loader import load_prompt
from docgen_core.services.llm import create_llm_model
from docgen_core.tools.files import list_files, read_file
from docgen_core.tools.search import search_code


class SubplanOutput(pydantic.BaseModel):
    section_id: str = pydantic.Field(
        description="Section id this subplan covers (must match input)"
    )
    page_specs: list[PageSpec] = pydantic.Field(
        description="3-7 page specs scoped to this section",
    )


def create_subplanner_agent(
    llm_config: LLMConfig,
    prompt_path: Path,
    output_language: str = "en",
) -> tuple[pydantic_ai.Agent[DocGenDeps, SubplanOutput], AgentConfig]:
    """Per-section planner with hybrid context.

    The subplan handler pre-fetches scope listings + key file snippets +
    search-seed results and embeds them in the user prompt as a baseline.
    Tools are still wired so the agent can drill deeper if the embedded
    context is insufficient. ``strict_dedupe=True`` on the deps prevents
    weak models from looping on identical calls.
    """
    prompt_config = load_prompt(prompt_path)
    model = create_llm_model(llm_config)

    instructions = prompt_config.instructions + build_directive(output_language, "subplanner")
    agent = pydantic_ai.Agent(
        model=model,
        deps_type=DocGenDeps,
        output_type=SubplanOutput,
        instructions=instructions,
        retries=prompt_config.max_result_retries,
        history_processors=[truncate_old_tool_results],
    )

    list_files_retries = prompt_config.tool_retries.get("list_files", 2)
    read_file_retries = prompt_config.tool_retries.get("read_file", 2)
    search_code_retries = prompt_config.tool_retries.get("search_code", 3)

    agent.tool(retries=list_files_retries)(list_files)
    agent.tool(retries=read_file_retries)(read_file)
    agent.tool(retries=search_code_retries)(search_code)

    return agent, prompt_config
