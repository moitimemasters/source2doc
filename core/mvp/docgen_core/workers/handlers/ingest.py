from pathlib import Path
import typing as tp
from uuid import UUID

from source2doc import storage
from source2doc.logging import get_logger

from docgen_core.pipeline import incremental as incremental_mod
from docgen_core.pipeline import ingest as ingest_pipeline
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod


logger = get_logger(__name__)


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    ctx.generation_id = data["generation_id"]
    repo_id = data.get("repo_id")
    path = data.get("path")
    name = data.get("name")
    description = data.get("description")
    # B2.4 — opt-in full reindex flag plumbed via the ``generation.requested``
    # payload (mirrored from the encrypted user_config so it survives
    # restart/resume). Defaults to False so existing tasks pick up the
    # incremental fast path automatically.
    force_reindex = bool(data.get("force_reindex") or False)

    filesystem = _resolve_filesystem(env, repo_id, path)
    repository_uuid = _coerce_uuid(repo_id)
    generation_uuid = _coerce_uuid(ctx.generation_id)

    # B2.4 / ТЗ ИНТ-04, ИНД-06 — load the prior hash snapshot and the
    # collection the previous generation left behind. Both are best-effort:
    # the first ingest of a repo gets `existing_hashes={}` and skips the
    # carry-over phase entirely. ``force_reindex`` short-circuits the
    # lookup so every file is re-chunked + re-embedded.
    existing_hashes: dict[str, str] = {}
    previous_collection: str | None = None
    if repository_uuid is not None and not force_reindex:
        existing_hashes = await env.storage.get_file_hashes(repository_uuid)
        if existing_hashes:
            prev_gen = await env.storage.latest_generation_for_repo(repository_uuid)
            if prev_gen is not None:
                previous_collection = f"docgen_{prev_gen}"

    new_collection = env.config.qdrant.collection
    copier: incremental_mod.AsyncQdrantPointCopier | None = None
    if (
        repository_uuid is not None
        and existing_hashes
        and previous_collection is not None
        and previous_collection != new_collection
    ):
        copier = incremental_mod.AsyncQdrantPointCopier(
            url=env.config.qdrant.url,
            api_key=env.config.qdrant.api_key,
        )

    logger.info(
        "starting_ingest",
        repo_id=repo_id,
        path=path,
        force_reindex=force_reindex,
        incremental=copier is not None,
        previous_collection=previous_collection,
        existing_hashes=len(existing_hashes),
    )

    # Pre-create the new Qdrant collection so the incremental copy phase
    # has somewhere to upsert into. Without this, every "carry unchanged
    # file" upsert hits 404 and falls back to re-embedding — wasting LLM
    # quota and spamming ``incremental.upsert_failed`` warnings.
    if copier is not None:
        try:
            await env.vectorstore.ensure_collection()
        except Exception as exc:  # noqa: BLE001 — defensive, matches caller style
            logger.warning(
                "ingest_ensure_collection_failed",
                error=str(exc),
                collection=new_collection,
            )

    try:
        try:
            result = await ingest_pipeline.ingest_codebase(
                filesystem,
                env.config.generation.chunk_size,
                env.config.generation.chunk_overlap,
                env.config.generation.overlap_lines_divisor,
                env.event_bus,
                existing_hashes=existing_hashes,
                previous_collection=previous_collection,
                new_collection=new_collection,
                qdrant_copier=copier,
            )
        except ingest_pipeline.EmptyCorpusError as exc:
            logger.warning(
                "ingest_empty_corpus",
                reason=exc.reason,
                files_count=exc.files_count,
                chunks_count=exc.chunks_count,
            )
            await env.event_bus.emit(
                "ingest.failed",
                {
                    "generation_id": ctx.generation_id,
                    "reason": exc.reason,
                    "files_count": exc.files_count,
                    "chunks_count": exc.chunks_count,
                },
            )
            # Re-raise so the consumer's outer try/except emits task.failed
            # and halts the pipeline. No ingest.completed → no plan/write.
            raise
    finally:
        if copier is not None:
            await copier.aclose()

    # Persist the per-file hashes so the next generation can take the fast
    # path. Done after a successful ingest only — failed runs leave the
    # prior snapshot intact so retries see the same baseline.
    if repository_uuid is not None and generation_uuid is not None and result.file_hashes:
        try:
            await env.storage.record_file_hashes(
                repository_uuid,
                generation_uuid,
                result.file_hashes,
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            # Never let a hash-table write failure break the docgen run.
            # Worst case the next ingest re-embeds everything.
            logger.warning(
                "record_file_hashes_failed",
                repository_id=str(repository_uuid),
                generation_id=str(generation_uuid),
                error=str(exc),
            )

    ctx.dominant_language = result.dominant_language
    await _emit_completed(
        env,
        ctx.generation_id,
        result,
        repo_id,
        path,
        name,
        description,
        iterative=data.get("iterative"),
    )


def _resolve_filesystem(
    env: env_mod.DocGenEnv,
    repo_id: str | None,
    path: str | None,
) -> storage.FileSystem:
    if repo_id:
        if not env.s3_config:
            raise ValueError("S3 config required for repo_id")
        return storage.S3FileSystem(env.s3_config, repo_id)
    if path:
        return storage.LocalFileSystem(Path(path))
    raise ValueError("Either repo_id or path must be provided")


def _coerce_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        # CLI dev runs sometimes pass non-UUID identifiers; fall back to
        # full-reindex semantics rather than crashing.
        logger.warning("id_not_uuid_falling_back_to_full_ingest", value=value)
        return None


async def _emit_completed(
    env: env_mod.DocGenEnv,
    generation_id: str,
    result: ingest_pipeline.IngestResult,
    repo_id: str | None,
    path: str | None,
    name: str | None = None,
    description: str | None = None,
    iterative: dict | None = None,
) -> None:
    await env.event_bus.emit(
        "ingest.completed",
        {
            "generation_id": generation_id,
            "chunks_count": len(result.chunks),
            "chunks": [chunk.model_dump() for chunk in result.chunks],
            "dominant_language": result.dominant_language,
            "language_counts": result.language_counts,
            "repo_id": repo_id,
            "path": path,
            "name": name,
            "description": description,
            # Forward the iterative-mode envelope (base_generation_id,
            # changed_files, deleted_files) downstream untouched. The
            # index handler reads it to decide whether to emit
            # ``index.completed`` or ``iterative.index_completed``.
            "iterative": iterative,
            # B2.4 — observability: how many files we managed to skip this
            # run and how many fresh chunks went on to the embedder.
            "incremental_summary": {
                "carried_over_files": len(result.carried_over_files),
                "fresh_chunks": len(result.chunks),
                "tracked_files": len(result.file_hashes),
            },
        },
    )
