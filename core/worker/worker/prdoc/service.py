"""Agent orchestration for the prdoc worker mode.

Splits ``process_prdoc_task`` cleanly: this module owns RAG fetch + the
Pydantic-AI run, the processor module owns the Redis/storage/event glue.
The split makes it trivial to mock ``run_prdoc_agent`` in tests without
spinning up an LLM.
"""

from __future__ import annotations

import contextlib
import typing as tp

from source2doc.config import EmbeddingsConfig, LLMConfig, QdrantConfig
from source2doc.logging import get_logger

from worker.prdoc import agent as agent_mod


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# RAG hook
# ---------------------------------------------------------------------------


async def _embed_query(embeddings_cfg: EmbeddingsConfig, text: str) -> list[float]:
    """Embed a single text via the OpenAI-compatible embeddings endpoint."""

    # Lazy import — embeddings are optional and we don't want to drag the
    # OpenAI client into the prdoc path when ``repo_id`` is absent.
    from docgen_core.services.embeddings.openai import OpenAIEmbeddings

    service = OpenAIEmbeddings(embeddings_cfg)
    return await service.embed_text(text)


async def _qdrant_collection_exists(qdrant_cfg: QdrantConfig, collection: str) -> bool:
    """Return True iff the Qdrant collection exists. Best-effort; on any
    error we conservatively answer False so the agent runs without RAG."""

    try:
        import qdrant_client

        client = qdrant_client.AsyncQdrantClient(url=qdrant_cfg.url, api_key=qdrant_cfg.api_key)
        try:
            collections = await client.get_collections()
            return any(c.name == collection for c in collections.collections)
        finally:
            with contextlib.suppress(Exception):
                await client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("qdrant_collection_check_failed", error=str(exc), collection=collection)
        return False


async def _semantic_search_chunks(
    *,
    qdrant_cfg: QdrantConfig,
    collection: str,
    query_vector: list[float],
    file_path: str,
    limit: int,
) -> list[str]:
    """Return up to ``limit`` chunk ``content`` strings for ``file_path``.

    Uses a payload filter on ``file_path`` so the snippets are scoped to the
    file the diff touches. Mirrors the pattern in
    ``app.routes.search.service`` without taking a hard dependency on the
    gateway package.
    """

    import qdrant_client
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = qdrant_client.AsyncQdrantClient(url=qdrant_cfg.url, api_key=qdrant_cfg.api_key)
    try:
        flt = Filter(
            must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))],
        )
        response = await client.query_points(
            collection_name=collection,
            query=list(query_vector),
            query_filter=flt,
            limit=limit,
            with_payload=True,
        )
        snippets: list[str] = []
        for point in getattr(response, "points", []) or []:
            payload = getattr(point, "payload", None) or {}
            content = payload.get("content")
            if content:
                snippets.append(str(content))
        return snippets
    finally:
        with contextlib.suppress(Exception):
            await client.close()


async def fetch_rag_context(
    *,
    embeddings_cfg: EmbeddingsConfig | None,
    qdrant_cfg: QdrantConfig | None,
    repo_id: str | None,
    changed_files: list[dict[str, tp.Any]],
    per_file_limit: int = 3,
    max_total_chunks: int = 30,
) -> dict[str, list[str]]:
    """Fetch up to ``per_file_limit`` Qdrant snippets per changed file.

    Returns an empty dict if RAG is disabled (no ``repo_id``, no embeddings
    config, no qdrant config, or the collection does not exist). The
    returned dict is keyed by file path and contains plain text snippets
    suitable for the agent prompt.
    """

    if not repo_id or embeddings_cfg is None or qdrant_cfg is None:
        return {}

    # ``docgen_{repo_id}`` is *not* the convention — collections are minted
    # per generation_id (``docgen_{generation_id}``). For the prdoc path
    # the indexed collection that matters is the one for the repo's most
    # recent bundle. We probe the canonical name first and fall back to a
    # repo-id-keyed name so callers can pre-seed a dedicated prdoc index.
    candidate_collections = [
        f"docgen_{repo_id}",
        f"prdoc_{repo_id}",
    ]
    collection: str | None = None
    for candidate in candidate_collections:
        if await _qdrant_collection_exists(qdrant_cfg, candidate):
            collection = candidate
            break

    if collection is None:
        logger.info(
            "prdoc_rag_skipped_no_collection",
            repo_id=repo_id,
            tried=candidate_collections,
        )
        return {}

    snippets_by_file: dict[str, list[str]] = {}
    remaining = max_total_chunks
    for entry in changed_files:
        if remaining <= 0:
            break
        path = entry.get("path")
        if not path:
            continue
        # Use the diff (or full content as a fallback) as the query — the
        # actual code text is more useful than the path alone.
        query = (entry.get("diff") or "")[:2000]
        if not query:
            query = (entry.get("full_content_after") or "")[:2000]
        if not query:
            continue

        try:
            vector = await _embed_query(embeddings_cfg, query)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "prdoc_rag_embed_failed", path=path, error=str(exc)
            )
            continue

        try:
            snippets = await _semantic_search_chunks(
                qdrant_cfg=qdrant_cfg,
                collection=collection,
                query_vector=vector,
                file_path=path,
                limit=min(per_file_limit, remaining),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "prdoc_rag_search_failed", path=path, error=str(exc)
            )
            continue

        if snippets:
            snippets_by_file[path] = snippets
            remaining -= len(snippets)

    return snippets_by_file


# ---------------------------------------------------------------------------
# Agent run
# ---------------------------------------------------------------------------


async def run_prdoc_agent(
    *,
    llm_config: LLMConfig,
    title: str | None,
    description: str | None,
    base_sha: str | None,
    head_sha: str | None,
    changed_files: list[dict[str, tp.Any]],
    rag_snippets_by_file: dict[str, list[str]] | None,
) -> agent_mod.PRDocSummary:
    """Run the Pydantic-AI agent and return the structured ``PRDocSummary``.

    Tests should patch this function directly (see
    ``core/worker/tests/prdoc/test_processor.py``) to bypass the LLM call.
    """

    agent = agent_mod.create_prdoc_agent(llm_config)
    prompt = agent_mod.build_prompt(
        title=title,
        description=description,
        base_sha=base_sha,
        head_sha=head_sha,
        changed_files=changed_files,
        rag_snippets_by_file=rag_snippets_by_file,
    )
    result = await agent.run(prompt)
    summary = result.output
    # Backstop: if the model under-counts, reset to the actual file count.
    if summary.files_summarised <= 0:
        summary.files_summarised = len(changed_files)
    return summary
