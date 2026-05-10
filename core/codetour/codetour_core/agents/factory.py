from pathlib import Path

import pydantic_ai

from source2doc.config import LLMConfig
from source2doc.tools.files import read_file
from source2doc.tools.git import get_authorship, get_history
from source2doc.tools.search import search_code

from codetour_core.agents.deps import CodetourDeps
from codetour_core.config import agents as agents_config
from codetour_core.config.loader import load_prompt
from codetour_core.services.llm import create_llm_model


def create_codetour_agent(
    llm_config: LLMConfig,
    prompt_path: Path,
    *,
    enable_read_file: bool = True,
    enable_git: bool = False,
) -> tuple[pydantic_ai.Agent[CodetourDeps, str], agents_config.CodetourGeneratorConfig]:
    """Create a Pydantic-AI agent for Code Tour generation.

    The agent returns a free-form string (parsed downstream as JSON) and has
    access to ``search_code`` (RAG over Qdrant). ``read_file`` is registered
    only when ``enable_read_file=True`` (i.e. a filesystem is mounted) so the
    agent does not waste tokens calling a tool it cannot use. The git-aware
    tools (``get_history``, ``get_authorship``) require ``enable_git=True`` —
    they fail loudly with ModelRetry if the underlying repo has no ``.git``.
    """

    prompt_config = load_prompt(prompt_path)
    model = create_llm_model(llm_config)

    agent = pydantic_ai.Agent(
        model=model,
        deps_type=CodetourDeps,
        output_type=str,
        system_prompt=prompt_config.system_prompt,
        retries=prompt_config.max_result_retries,
    )

    search_code_retries = prompt_config.tool_retries.get("search_code", 5)
    agent.tool(retries=search_code_retries)(search_code)

    if enable_read_file:
        read_file_retries = prompt_config.tool_retries.get("read_file", 3)
        agent.tool(retries=read_file_retries)(read_file)

    if enable_git:
        history_retries = prompt_config.tool_retries.get("get_history", 3)
        authorship_retries = prompt_config.tool_retries.get("get_authorship", 3)
        agent.tool(retries=history_retries)(get_history)
        agent.tool(retries=authorship_retries)(get_authorship)

    return agent, prompt_config
