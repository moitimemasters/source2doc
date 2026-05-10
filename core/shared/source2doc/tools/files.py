import pydantic_ai

from source2doc.logging import get_logger


logger = get_logger(__name__)


# Hard cap on content returned from read_file in a single call. Prevents the
# agent from flooding its context with one large file.
DEFAULT_MAX_LINES = 200
TRUNCATION_MARKER = (
    "\n\n... [truncated — call read_file again with start_line / end_line "
    "to read a specific range of this file]"
)


# Hard cap on the list returned to the agent. A 1k+ file repo (httpx
# style) blows up the model's context if the entire flat listing is fed
# back into the conversation; cap aggressively and surface the count so
# the planner can refine the path/pattern. Lowered from 200 → 120 after
# observing context blow-ups on multi-call agents.
MAX_LIST_FILES_ENTRIES = 120


async def list_files(
    ctx: pydantic_ai.RunContext,
    path: str = ".",
    pattern: str = "*",
) -> list[str]:
    agent_name = ctx.deps.agent_name
    invocation_id = getattr(ctx.deps, "invocation_id", "?")
    filesystem = ctx.deps.filesystem

    logger.info(
        "tool_called",
        tool="list_files",
        agent=agent_name,
        invocation_id=invocation_id,
        path=path,
        pattern=pattern,
    )

    # Hard dedupe: every repeat raises ModelRetry. Weak models that
    # ignore the warning will burn the per-tool retry budget and fail the
    # page cleanly — much cheaper than silently returning cached content
    # while the model accumulates dozens of redundant round-trips.
    if getattr(ctx.deps, "strict_dedupe", False):
        call_key = f"{agent_name}:list_files:{path}:{pattern}"
        log: set[str] = ctx.deps.tool_call_log
        if call_key in log:
            raise pydantic_ai.ModelRetry(
                f"You already called list_files(path={path!r}, pattern={pattern!r}) "
                f"earlier in this run. Re-calling it returns the same listing and "
                f"costs an LLM round-trip. Use the previous result; if you need a "
                f"different view, change ``path`` or ``pattern``. Otherwise, emit "
                f"your final structured output now."
            )
        log.add(call_key)

    result = await filesystem.list_files(path, pattern)
    truncated = False
    if len(result) > MAX_LIST_FILES_ENTRIES:
        truncated = True
        suffix_hint = (
            f"... [truncated — {len(result) - MAX_LIST_FILES_ENTRIES} "
            "more entries; refine path/pattern to narrow the listing]"
        )
        result = list(result[:MAX_LIST_FILES_ENTRIES]) + [suffix_hint]

    logger.info(
        "tool_result",
        tool="list_files",
        agent=agent_name,
        invocation_id=invocation_id,
        files_count=len(result),
        truncated=truncated,
    )
    return result


async def read_file(
    ctx: pydantic_ai.RunContext,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read a file, optionally restricted to a 1-based inclusive line range.

    Without an explicit range the first ``DEFAULT_MAX_LINES`` lines are returned
    and a marker tells the agent it can request more.
    Cached in ``ctx.deps.file_cache`` to avoid redundant S3 reads within a run.
    """

    agent_name = ctx.deps.agent_name
    invocation_id = getattr(ctx.deps, "invocation_id", "?")
    filesystem = ctx.deps.filesystem
    cache: dict[str, str] = ctx.deps.file_cache

    logger.info(
        "tool_called",
        tool="read_file",
        agent=agent_name,
        invocation_id=invocation_id,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
    )

    if filesystem is None:
        raise pydantic_ai.ModelRetry(
            "No filesystem is mounted for this run — read_file is unavailable. "
            "Use only search_code to ground your answer."
        )

    # Hard dedupe keyed by (path, range) — different ranges of the same
    # file are NOT duplicates. Every repeat raises ModelRetry; the per-tool
    # retry budget then fails the page if the model keeps looping.
    if getattr(ctx.deps, "strict_dedupe", False):
        call_key = f"{agent_name}:read_file:{file_path}:{start_line}:{end_line}"
        log: set[str] = ctx.deps.tool_call_log
        if call_key in log:
            raise pydantic_ai.ModelRetry(
                f"You already called read_file({file_path!r}, start_line="
                f"{start_line}, end_line={end_line}) earlier in this run. "
                f"Re-reading the same range costs an LLM round-trip. Use the "
                f"previous result, request a different range, or emit your "
                f"final structured output now."
            )
        log.add(call_key)

    cache_key = f"{agent_name}:{file_path}"
    if cache_key in cache:
        content = cache[cache_key]
        logger.info(
            "tool_cache_hit",
            tool="read_file",
            agent=agent_name,
            invocation_id=invocation_id,
            file_path=file_path,
        )
    else:
        if not await filesystem.file_exists(file_path):
            raise pydantic_ai.ModelRetry(
                f"File '{file_path}' does not exist. "
                f"Use list_files or search_code to find the correct file path."
            )

        try:
            content = await filesystem.read_file(file_path)
        except UnicodeDecodeError as e:
            raise pydantic_ai.ModelRetry(
                f"File '{file_path}' is not a text file or has encoding issues.",
            ) from e

        cache[cache_key] = content

    # Iterative-mode classifier needs to know which files each page touched.
    # ``touched_files`` is the union across read_file + search_code hits;
    # the writer handler persists it to ``documentation_pages.source_files``
    # at finalize time. Old DocGenDeps (custom subclasses) without the
    # field degrade silently — getattr returns None.
    touched: set[str] | None = getattr(ctx.deps, "touched_files", None)
    if touched is not None:
        touched.add(file_path)

    lines = content.splitlines()
    total_lines = len(lines)

    if start_line is not None or end_line is not None:
        start_idx = max(1, start_line or 1) - 1
        end_idx = end_line if end_line is not None else total_lines
        end_idx = min(end_idx, total_lines)
        if start_idx >= total_lines:
            raise pydantic_ai.ModelRetry(
                f"start_line={start_line} is past the end of '{file_path}' "
                f"(file has {total_lines} lines)."
            )
        sliced = lines[start_idx:end_idx]
        result = "\n".join(sliced)
        truncated = False
    elif total_lines > DEFAULT_MAX_LINES:
        result = "\n".join(lines[:DEFAULT_MAX_LINES]) + TRUNCATION_MARKER
        truncated = True
    else:
        result = content
        truncated = False

    logger.info(
        "tool_result",
        tool="read_file",
        agent=agent_name,
        invocation_id=invocation_id,
        chars_count=len(result),
        total_lines=total_lines,
        truncated=truncated,
    )
    return result
