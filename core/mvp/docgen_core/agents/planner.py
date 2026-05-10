from pathlib import Path

import pydantic
import pydantic_ai

from source2doc.agents.history import truncate_old_tool_results
from source2doc.config import LLMConfig

from docgen_core.agents.deps import DocGenDeps
from docgen_core.agents.language_directive import build_directive
from docgen_core.config.agents import AgentConfig
from docgen_core.config.loader import load_prompt
from docgen_core.services.llm import create_llm_model
from docgen_core.tools.files import list_files, read_file
from docgen_core.tools.search import search_code


class PageSpec(pydantic.BaseModel):
    page_id: str = pydantic.Field(description="Unique page identifier (will be filename)")
    title: str = pydantic.Field(description="Page title")
    description: str = pydantic.Field(description="What this page covers")
    search_queries: list[str] = pydantic.Field(description="Queries to find relevant code")
    # Subplanner discovers relevant files while researching the section.
    # Capturing them here lets the writer prompt prefill those files
    # instead of forcing the writer agent to re-discover them via tools.
    # Optional for backward compatibility (legacy plans have empty list).
    primary_files: list[str] = pydantic.Field(
        default_factory=list,
        description=(
            "1-4 repository-relative file paths most central to this page. "
            "Subplanner fills these from its own search_code/read_file work; "
            "the writer prompt receives their contents preloaded so the "
            "writer doesn't have to re-fetch them."
        ),
    )


class SectionSpec(pydantic.BaseModel):
    id: str = pydantic.Field(description="Kebab-case section slug, used as nav key")
    title: str = pydantic.Field(description="Section title shown in navigation")
    description: str = pydantic.Field(
        description="1-2 sentence English summary of what this section covers"
    )
    scope_paths: list[str] = pydantic.Field(
        description="1-3 directories or files the subplanner should focus on"
    )
    search_seeds: list[str] = pydantic.Field(
        description="2-3 seed search queries the subplanner can refine"
    )


class PlanOutline(pydantic.BaseModel):
    project_summary: str = pydantic.Field(
        description="1-3 sentence English description of the project"
    )
    sections: list[SectionSpec] = pydantic.Field(
        description="6-12 sections covering the codebase, each scoped to 1-3 top-level dirs",
    )


def create_planner_agent(
    llm_config: LLMConfig,
    prompt_path: Path,
    output_language: str = "en",
) -> tuple[pydantic_ai.Agent[DocGenDeps, PlanOutline], AgentConfig]:
    """Top-planner with hybrid context: pre-fetched listing + README is embedded
    in the user prompt as a baseline, but list_files / read_file / search_code
    are still wired so the agent can drill down into anything that surprises
    it. ``strict_dedupe=True`` on the deps keeps weak models from looping on
    identical tool calls.
    """
    prompt_config = load_prompt(prompt_path)
    model = create_llm_model(llm_config)

    instructions = prompt_config.instructions + build_directive(output_language, "planner")
    agent = pydantic_ai.Agent(
        model=model,
        deps_type=DocGenDeps,
        output_type=PlanOutline,
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
