import typing as tp

from source2doc.logging import get_logger
from source2doc.models import chunks as chunk_models

from docgen_core.pipeline import index as index_pipeline
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod


logger = get_logger(__name__)


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    chunks_data = data["chunks"]

    # B2.4 — chunks for files that haven't changed since the previous
    # generation aren't in this list anymore (the ingest handler copied
    # their points across collections directly). We just embed + upsert
    # whatever made it through.
    logger.info("starting_indexing", chunks_count=len(chunks_data))

    chunks = [chunk_models.CodeChunk(**chunk_data) for chunk_data in chunks_data]

    await index_pipeline.index_chunks(
        chunks,
        env.embeddings,
        env.vectorstore,
        env.event_bus,
        env.config.embeddings.batch_size,
        env.config.embeddings.concurrency,
    )

    iterative = data.get("iterative")
    # In iterative mode the planner is skipped — emit a distinct event so
    # only the iterative orchestrator picks up the baton. The plan handler
    # remains subscribed to ``index.completed`` for full-mode generations.
    completion_event = "iterative.index_completed" if iterative else "index.completed"
    await env.event_bus.emit(
        completion_event,
        {
            "generation_id": generation_id,
            "chunks_count": len(chunks),
            "repo_id": data.get("repo_id"),
            "path": data.get("path"),
            "name": data.get("name"),
            "description": data.get("description"),
            "iterative": iterative,
        },
    )
