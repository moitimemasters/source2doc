import pydantic
import pydantic_ai

from source2doc.logging import get_logger
from source2doc.models.chunks import CodeChunk


logger = get_logger(__name__)


# Absolute upper bound the model can request via the `limit` parameter.
MAX_SEARCH_LIMIT = 15

# Per-chunk content cap. Each tool result lands in the agent's
# conversation history; a few dozen large chunks blow the model's
# context window. Truncate each chunk's content to this many characters
# (≈ 200 tokens) and append a marker so the agent knows the rest is
# available via ``read_file``. Lowered from 1500 → 800 after qwen3-coder
# blew its 262k context on a single page that called search_code 10+ times.
MAX_CHUNK_CHARS = 500
TRUNCATION_MARKER = "\n... [truncated — call read_file with this file_path for more]"


class SearchResult(pydantic.BaseModel):
    """Soft tool output. Empty ``chunks`` is a normal answer, not a retry.

    The agent should treat ``chunks=[]`` as evidence that the topic is not
    covered by the indexed corpus and either rephrase the search or omit
    the section. ``hint`` is plain English advice for the model.
    """

    chunks: list[CodeChunk]
    hint: str = ""


def _truncated_chunk(chunk: CodeChunk) -> CodeChunk:
    if len(chunk.content) <= MAX_CHUNK_CHARS:
        return chunk
    return chunk.model_copy(
        update={"content": chunk.content[:MAX_CHUNK_CHARS] + TRUNCATION_MARKER}
    )


def _truncate_chunks(chunks: list[CodeChunk]) -> list[CodeChunk]:
    return [_truncated_chunk(c) for c in chunks]


async def search_code(
    ctx: pydantic_ai.RunContext,
    query: str,
    limit: int | None = None,
) -> SearchResult:
    """Semantic search over the indexed codebase.

    Requires ``ctx.deps`` to expose ``embeddings``, ``vectorstore``,
    ``generation_config`` (with ``search_limit``) and a ``search_cache``
    dict. Empty queries and exact-cache repeats raise ``ModelRetry``
    (true misuses). Empty Qdrant results are returned as ``SearchResult``
    with a hint — they do NOT count toward the retry budget, so a writer
    can gracefully omit a missing section instead of being killed by
    ``UnexpectedModelBehavior`` after 5 zero-hit queries.
    """

    agent_name = ctx.deps.agent_name
    invocation_id = getattr(ctx.deps, "invocation_id", "?")
    embeddings = ctx.deps.embeddings
    vectorstore = ctx.deps.vectorstore
    default_limit: int = ctx.deps.generation_config.search_limit
    cache: dict[tuple[str, str, int], list[CodeChunk]] = ctx.deps.search_cache

    normalized_query = query.strip()
    if not normalized_query:
        raise pydantic_ai.ModelRetry(
            "search_code was called with an empty query. Pass a meaningful "
            "search string (e.g. a class name, function, or concept)."
        )

    effective_limit = default_limit if limit is None else min(max(1, limit), MAX_SEARCH_LIMIT)
    # Agent-name namespaced cache key — defense in depth so a deps object
    # accidentally shared across agent types cannot cross-pollute results.
    cache_key = (agent_name, normalized_query, effective_limit)

    logger.info(
        "tool_called",
        tool="search_code",
        agent=agent_name,
        invocation_id=invocation_id,
        query=normalized_query,
        limit=effective_limit,
    )

    if cache_key in cache:
        cached_chunks = cache[cache_key]
        if getattr(ctx.deps, "strict_dedupe", False):
            # Hard dedupe: every repeat raises ModelRetry, not just the first.
            # Weak models that keep looping will exhaust ``tool_retries`` and
            # fail the page rather than burning hundreds of round-trips on
            # cached results.
            raise pydantic_ai.ModelRetry(
                f"You already searched for '{normalized_query}' (limit="
                f"{effective_limit}) earlier in this run. Re-running the "
                f"same query returns identical chunks and costs an LLM "
                f"round-trip. Either diversify (different class/function "
                f"name, broader concept) or emit your final structured "
                f"output now."
            )
        logger.info(
            "tool_cache_hit",
            tool="search_code",
            agent=agent_name,
            invocation_id=invocation_id,
            query=normalized_query,
            chunks_count=len(cached_chunks),
        )
        # Soft hint for non-strict agents (writer, critic, diagrammer): they
        # may legitimately re-query the same term across long runs, and a hard
        # ModelRetry there would blow up the page rather than nudge the agent.
        hint = (
            f"You already searched for '{normalized_query}' earlier in this "
            f"run and the results are the same. Diversify your queries "
            f"(different keywords, class names, concepts) instead of "
            f"repeating this one."
        )
        return SearchResult(chunks=_truncate_chunks(cached_chunks), hint=hint)

    query_vector = await embeddings.embed_text(normalized_query)
    chunks = await vectorstore.search(query_vector, effective_limit)
    cache[cache_key] = chunks

    # Iterative-mode classifier reads ``touched_files`` after the writer
    # finishes a page so the per-page ``source_files`` array reflects every
    # file the agent actually grounded on (whether via direct read_file or
    # via search hits whose chunks pointed at this file).
    touched: set[str] | None = getattr(ctx.deps, "touched_files", None)
    if touched is not None:
        for chunk in chunks:
            file_path = getattr(chunk.span, "file_path", None) or getattr(chunk, "file_path", None)
            if file_path:
                touched.add(file_path)

    if not chunks:
        hint = (
            f"No code chunks matched '{normalized_query}'. The corpus may not cover "
            f"this topic. Try alternative keywords (different class/function names, "
            f"broader concept, related terminology) or omit the section if it is "
            f"genuinely absent from the repository."
        )
        logger.info(
            "tool_result",
            tool="search_code",
            agent=agent_name,
            invocation_id=invocation_id,
            chunks_count=0,
            soft_empty=True,
        )
        return SearchResult(chunks=[], hint=hint)

    logger.info(
        "tool_result",
        tool="search_code",
        agent=agent_name,
        invocation_id=invocation_id,
        chunks_count=len(chunks),
    )
    return SearchResult(chunks=_truncate_chunks(chunks))
