import pydantic


class BaseAgentConfig(pydantic.BaseModel):
    """Shared schema for prompt/agent YAML configs.

    Both docgen and codetour agents reuse this shape: instructions text,
    per-tool retry counts, output validation retries, hard timeout, response
    token limit, and an outer retry budget.
    """

    instructions: str | None = pydantic.Field(
        default=None,
        description="Agent instructions (system prompt). Optional for agents that "
        "use a separate system_prompt + user_prompt_template split.",
    )
    tools: list[str] = pydantic.Field(default_factory=list)
    tool_retries: dict[str, int] = pydantic.Field(default_factory=dict)
    max_result_retries: int = pydantic.Field(default=1, ge=0)
    timeout_seconds: int = pydantic.Field(default=120, gt=0)
    # ``None`` disables the per-run output-token cap — the LLM provider's
    # own ``max_tokens`` (from ``LLMConfig``) is the only ceiling. Set an
    # int here only if you want a stricter agent-side cap; the gateway
    # default is "no cap" so a slightly chatty plan/critic doesn't kill
    # the whole generation.
    response_tokens_limit: int | None = pydantic.Field(default=None)
    # Hard cap on the number of LLM round-trips the agent may make in a single
    # ``agent.run`` call. Stops degenerate models from looping forever on tool
    # calls (planner repeatedly calling list_files, etc.). Set to ``None`` to
    # disable the cap entirely. Bumping this is cheap; for large repos the
    # planner legitimately needs 30–60 tool round-trips before it has enough
    # context.
    request_limit: int | None = pydantic.Field(default=30)
    max_attempts: int = pydantic.Field(default=2, ge=1)
    # Process-wide cap on concurrent ``agent.run`` invocations across
    # all agents. Resolved at runtime from ``GenerationConfig.llm_concurrency``
    # (``runner.run_agent`` reads this field directly). Default 5
    # matches Eliza's inflight limit; bumping it for self-hosted
    # providers without a sharp limit is fine.
    llm_concurrency: int = pydantic.Field(default=5, ge=1)
