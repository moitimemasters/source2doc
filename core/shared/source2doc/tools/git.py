import pydantic_ai

from source2doc.logging import get_logger


logger = get_logger(__name__)


async def get_authorship(
    ctx: pydantic_ai.RunContext,
    file_path: str,
    start_line: int,
    end_line: int | None = None,
) -> dict:
    """Return primary author, last-modified date and full contributor list
    for a line range in a file. Surfaces git blame, so the agent can ground
    "this is owned by @X / last touched in March" claims in real metadata.
    """

    git_ctx = getattr(ctx.deps, "git_context", None)
    agent_name = getattr(ctx.deps, "agent_name", "unknown")
    logger.info(
        "tool_called",
        tool="get_authorship",
        agent=agent_name,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
    )

    if git_ctx is None or not await git_ctx.is_available():
        raise pydantic_ai.ModelRetry(
            "git history is unavailable for this repo (likely uploaded as a "
            "tarball without .git). Skip authorship references in your output."
        )

    info = await git_ctx.authorship(file_path, start_line, end_line)
    if info is None:
        raise pydantic_ai.ModelRetry(
            f"git blame returned nothing for {file_path}:{start_line}"
            f"{('-' + str(end_line)) if end_line else ''}. Either the file "
            f"isn't tracked or the range is past EOF — verify with read_file."
        )

    payload = info.to_dict()
    logger.info("tool_result", tool="get_authorship", agent=agent_name)
    return payload


async def get_history(
    ctx: pydantic_ai.RunContext,
    file_path: str,
    start_line: int,
    end_line: int | None = None,
    limit: int = 5,
) -> list[dict]:
    """Return the last N commits that touched the given line range. Each entry
    has ``sha``, ``short_sha``, ``author``, ``date`` (ISO-8601) and ``message``.
    Use the most relevant commit's message in your ``key_idea`` to explain the
    *why* behind the code.
    """

    git_ctx = getattr(ctx.deps, "git_context", None)
    agent_name = getattr(ctx.deps, "agent_name", "unknown")
    logger.info(
        "tool_called",
        tool="get_history",
        agent=agent_name,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        limit=limit,
    )

    if git_ctx is None or not await git_ctx.is_available():
        raise pydantic_ai.ModelRetry(
            "git history is unavailable for this repo. Skip commit references "
            "in your output."
        )

    commits = await git_ctx.history(
        file_path, start_line, end_line, limit=max(1, min(limit, 10))
    )
    if commits is None:
        raise pydantic_ai.ModelRetry(
            f"git log returned nothing for {file_path}:{start_line}"
            f"{('-' + str(end_line)) if end_line else ''}. Either the file "
            f"isn't tracked or the range is past EOF — verify with read_file."
        )
    if not commits:
        raise pydantic_ai.ModelRetry(
            f"No commits touched {file_path}:{start_line}"
            f"{('-' + str(end_line)) if end_line else ''}. Try a wider range "
            f"or skip the history reference for this step."
        )

    out = [c.to_dict() for c in commits]
    logger.info(
        "tool_result", tool="get_history", agent=agent_name, commits_count=len(out)
    )
    return out
