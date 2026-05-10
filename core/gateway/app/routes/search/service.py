"""Project-level search service.

Combines per-repository Qdrant collections (one per generation, named
``docgen_{generation_id}``) into a single search interface.

Two modes are supported:

* ``semantic`` — runs the configured embeddings model and uses Qdrant
  vector search (cosine).
* ``fulltext`` — uses the Qdrant ``MatchText`` payload filter against the
  chunk ``content`` field. Score is rank-based (1.0 - idx/total) because
  ``MatchText`` is a boolean filter, not a scored query.

Filters (``file_path``, ``directory``, ``language``) are applied as Qdrant
payload conditions in both modes.
"""

from __future__ import annotations

import contextlib
import dataclasses as dc
import typing as tp
from uuid import UUID

from fastapi import HTTPException, status

from source2doc.config import EmbeddingsConfig, QdrantConfig
from source2doc.logging import get_logger
from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage.presets import ConfigPresetStorage

from app.config import Config
from app.routes.search.dto import (
    SearchFilters,
    SearchHit,
    SearchMetadata,
    SearchRequest,
    SearchResponse,
    SearchSource,
)


logger = get_logger(__name__)


@dc.dataclass
class _ResolvedDefaults:
    """Embeddings + Qdrant config resolved from the default preset / app config."""

    embeddings: EmbeddingsConfig | None
    qdrant: QdrantConfig


# We keep this small protocol so tests can substitute a stub vector store
# without pulling in the real ``qdrant_client`` import path.
class QdrantSearchClient(tp.Protocol):
    async def query_points(self, **kwargs: tp.Any) -> tp.Any: ...

    async def scroll(self, **kwargs: tp.Any) -> tp.Any: ...

    async def close(self) -> None: ...


# Default factory — overridable from tests via dependency injection.
async def _default_qdrant_client_factory(qdrant: QdrantConfig) -> QdrantSearchClient:
    import qdrant_client

    return qdrant_client.AsyncQdrantClient(url=qdrant.url, api_key=qdrant.api_key)


async def _default_embed_text(
    config: EmbeddingsConfig,
    text: str,
) -> list[float]:
    # Imported lazily — gateway doesn't otherwise need the OpenAI client.
    import httpx
    from openai import AsyncOpenAI

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
        verify=False,
    )
    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        http_client=http_client,
    )
    try:
        response = await client.embeddings.create(model=config.model, input=text)
        return response.data[0].embedding
    finally:
        await http_client.aclose()


async def _resolve_defaults(
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
    app_qdrant: QdrantConfig,
) -> _ResolvedDefaults:
    """Pull embeddings + Qdrant from the default preset, falling back to app config."""

    embeddings: EmbeddingsConfig | None = None
    qdrant_overrides: dict[str, tp.Any] = {}

    default_preset = await presets.get_default()
    if default_preset is not None:
        try:
            preset_config = encryption.decrypt_config(default_preset.encrypted_config)
        except Exception as exc:
            logger.warning("preset_decrypt_failed", error=str(exc))
            preset_config = {}

        emb_block = preset_config.get("embeddings")
        if emb_block:
            with contextlib.suppress(Exception):
                embeddings = EmbeddingsConfig(**emb_block)

        qdrant_block = preset_config.get("qdrant")
        if qdrant_block:
            qdrant_overrides = qdrant_block

    qdrant = QdrantConfig(
        url=qdrant_overrides.get("url") or app_qdrant.url,
        collection=qdrant_overrides.get("collection") or app_qdrant.collection,
        api_key=qdrant_overrides.get("api_key") or app_qdrant.api_key,
    )
    return _ResolvedDefaults(embeddings=embeddings, qdrant=qdrant)


def _build_filter(
    filters: SearchFilters | None,
) -> tp.Any:
    """Return a Qdrant ``Filter`` (or None) for the supplied payload conditions."""

    from qdrant_client.models import FieldCondition, Filter, MatchText, MatchValue

    must: list[FieldCondition] = []

    if filters is None:
        return None

    if filters.file_path:
        must.append(
            FieldCondition(key="file_path", match=MatchValue(value=filters.file_path)),
        )

    if filters.directory:
        # Qdrant's MatchText is token-based; for a directory prefix we fall
        # back to substring-style matching on the file_path text. This is
        # adequate for the project-search UX and avoids splitting paths
        # into separate payload fields.
        must.append(
            FieldCondition(key="file_path", match=MatchText(text=filters.directory)),
        )

    if filters.language:
        must.append(
            FieldCondition(key="language", match=MatchValue(value=filters.language)),
        )

    if not must:
        return None
    return Filter(must=must)


def _payload_to_hit(
    payload: dict[str, tp.Any],
    score: float,
    repository_id: str,
) -> SearchHit:
    return SearchHit(
        text=payload.get("content", ""),
        score=score,
        source=SearchSource(
            file_path=payload.get("file_path", ""),
            start_line=int(payload.get("start_line", 0) or 0),
            end_line=int(payload.get("end_line", 0) or 0),
            language=payload.get("language"),
        ),
        metadata=SearchMetadata(
            repository_id=repository_id,
            chunk_id=payload.get("chunk_id"),
        ),
    )


async def _ensure_text_index(
    client: QdrantSearchClient,
    collection: str,
) -> None:
    """Ensure the ``content`` payload field is indexed for ``MatchText``.

    Qdrant requires fields used in ``MatchText`` filters to have a text
    payload index. The call is idempotent — Qdrant returns an OK response
    if the index already exists; any other error is logged and swallowed
    so a missing/transient index never breaks the request path.
    """

    try:
        from qdrant_client.models import PayloadSchemaType, TextIndexParams, TokenizerType

        await client.create_payload_index(  # type: ignore[attr-defined]
            collection_name=collection,
            field_name="content",
            field_schema=TextIndexParams(
                type=PayloadSchemaType.TEXT,
                tokenizer=TokenizerType.WORD,
                lowercase=True,
            ),
        )
    except Exception as exc:
        # Already-exists is the common case — Qdrant raises a 4xx that we
        # ignore. Anything else still shouldn't block the user; log it and
        # let the search proceed (which will surface a clearer error).
        logger.debug("ensure_text_index_skipped", collection=collection, error=str(exc))


async def _semantic_search(
    *,
    client: QdrantSearchClient,
    collection: str,
    query: str,
    embeddings: EmbeddingsConfig,
    payload_filter: tp.Any,
    limit: int,
    embed_text: tp.Callable[[EmbeddingsConfig, str], tp.Awaitable[list[float]]],
) -> list[tuple[dict[str, tp.Any], float]]:
    vector = await embed_text(embeddings, query)
    response = await client.query_points(
        collection_name=collection,
        query=list(vector),
        query_filter=payload_filter,
        limit=limit,
        with_payload=True,
    )
    out: list[tuple[dict[str, tp.Any], float]] = []
    for point in getattr(response, "points", []) or []:
        payload = getattr(point, "payload", None)
        if payload is None:
            continue
        score = float(getattr(point, "score", 0.0) or 0.0)
        out.append((payload, score))
    return out


async def _fulltext_search(
    *,
    client: QdrantSearchClient,
    collection: str,
    query: str,
    payload_filter: tp.Any,
    limit: int,
) -> list[tuple[dict[str, tp.Any], float]]:
    """Run a fulltext (boolean MatchText) search against the chunk content."""

    from qdrant_client.models import FieldCondition, Filter, MatchText

    text_condition = FieldCondition(key="content", match=MatchText(text=query))
    if payload_filter is None:
        scroll_filter = Filter(must=[text_condition])
    else:
        # Compose existing payload filters with the text match. We rebuild
        # rather than mutate so the caller's filter object stays clean.
        existing = list(getattr(payload_filter, "must", None) or [])
        scroll_filter = Filter(must=[*existing, text_condition])

    await _ensure_text_index(client, collection)

    points, _next = await client.scroll(
        collection_name=collection,
        scroll_filter=scroll_filter,
        limit=limit,
        with_payload=True,
    )
    out: list[tuple[dict[str, tp.Any], float]] = []
    total = max(len(points), 1)
    for idx, point in enumerate(points):
        payload = getattr(point, "payload", None)
        if payload is None:
            continue
        # Rank-based score keeps the response shape uniform with semantic
        # mode; first hit gets 1.0 and they decay linearly. Documented in
        # the module docstring.
        score = 1.0 - (idx / total)
        out.append((payload, score))
    return out


async def search_project(
    *,
    repository_id: str,
    request: SearchRequest,
    storage: PostgresStorage,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
    app_config: Config,
    qdrant_client_factory: tp.Callable[[QdrantConfig], tp.Awaitable[QdrantSearchClient]]
    | None = None,
    embed_text: tp.Callable[[EmbeddingsConfig, str], tp.Awaitable[list[float]]] | None = None,
) -> SearchResponse:
    # Resolve factories via module attribute lookup so tests can monkey-
    # patch ``_default_qdrant_client_factory`` / ``_default_embed_text``
    # after import without rebinding default arguments captured at def
    # time.
    if qdrant_client_factory is None:
        qdrant_client_factory = _default_qdrant_client_factory
    if embed_text is None:
        embed_text = _default_embed_text
    try:
        project_uuid = UUID(repository_id)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"project id must be a UUID, got: {repository_id}",
        )

    # The path param is named ``repository_id`` for backwards compat with the
    # frozen API contract, but the UI passes ``bundle.generation_id`` (the
    # value plumbed as ``projectId`` in the wiki). Resolve in two steps:
    #
    # 1. Try as a real ``repositories.id`` and pick its latest generation.
    # 2. Fall back to treating the value as a ``generation_id`` and pull the
    #    repo through the bundle row.
    repo = await storage.get_repository(project_uuid)
    if repo is not None:
        generation_ids = await storage.list_bundle_generation_ids_for_repo(
            project_uuid, limit=1
        )
        if not generation_ids:
            return SearchResponse(mode=request.mode, total=0, results=[])
        target_generation_id = generation_ids[0]
    else:
        bundle_repo = await storage.get_bundle_repository(project_uuid)
        if bundle_repo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project not found: {repository_id}",
            )
        target_generation_id = str(project_uuid)

    collection = f"docgen_{target_generation_id}"

    defaults = await _resolve_defaults(presets, encryption, app_config.qdrant)

    if request.mode == "semantic" and defaults.embeddings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Semantic search needs an embeddings config. Configure a default "
                "preset under /admin/presets or use mode='fulltext'."
            ),
        )

    payload_filter = _build_filter(request.filters)

    client = await qdrant_client_factory(defaults.qdrant)
    try:
        if request.mode == "semantic":
            assert defaults.embeddings is not None  # checked above
            raw = await _semantic_search(
                client=client,
                collection=collection,
                query=request.query,
                embeddings=defaults.embeddings,
                payload_filter=payload_filter,
                limit=request.limit,
                embed_text=embed_text,
            )
        else:
            raw = await _fulltext_search(
                client=client,
                collection=collection,
                query=request.query,
                payload_filter=payload_filter,
                limit=request.limit,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "search_qdrant_failed",
            collection=collection,
            mode=request.mode,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Vector store unavailable: {exc}",
        )
    finally:
        with contextlib.suppress(Exception):
            await client.close()

    hits = [_payload_to_hit(payload, score, repository_id) for payload, score in raw]
    return SearchResponse(mode=request.mode, total=len(hits), results=hits)
