"""Per-message processing for the prdoc worker.

Owns the Redis/storage/event glue: load encrypted task config, persist the
``running`` row, fetch RAG snippets, run the agent, persist the completed
summary, and emit per-generation events to the SSE stream.
"""

from __future__ import annotations

import json
from uuid import UUID

from source2doc.config import EmbeddingsConfig, LLMConfig, QdrantConfig
from source2doc.events.bus import annotate_event
from source2doc.logging import (
    bind_generation_context,
    bind_phase,
    bind_pipeline,
    clear_generation_context,
    get_logger,
)
from source2doc.pipelines import PRDOC
from source2doc.security.encryption import ConfigEncryption

from worker.prdoc import service as prdoc_service
from worker.prdoc.env import PRDocWorkerEnv
from worker.streams import consumer as consumer_mod


logger = get_logger(__name__)


PRDOC_EVENTS_TTL_SECONDS = 24 * 3600


def _events_stream(generation_id: UUID) -> str:
    return f"events:prdoc:{generation_id}"


def _make_event_emitter(redis, stream: str):
    async def emit(event_type: str, data: dict) -> None:
        # Stamp the per-task trace_id from contextvars so SSE consumers can
        # correlate events with the originating request.
        payload = dict(data)
        trace_id = consumer_mod.trace_id_from_context()
        if trace_id and "trace_id" not in payload:
            payload["trace_id"] = trace_id
        annotated = annotate_event(PRDOC, event_type, payload, logger)
        await redis.xadd(stream, {"type": event_type, "data": json.dumps(annotated)})
        await redis.expire(stream, PRDOC_EVENTS_TTL_SECONDS)

    return emit


async def _load_user_config(
    redis,
    encryption: ConfigEncryption,
    config_key: str,
) -> dict:
    encrypted = await redis.get(config_key)
    if not encrypted:
        raise RuntimeError(
            f"Encrypted prdoc config not found at {config_key} (cancelled or TTL expired?)"
        )
    return encryption.decrypt_config(encrypted)


def _resolve_embeddings(user_config: dict) -> EmbeddingsConfig | None:
    raw = user_config.get("embeddings")
    if not raw:
        return None
    try:
        return EmbeddingsConfig(**raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prdoc_embeddings_config_invalid", error=str(exc))
        return None


def _resolve_qdrant(user_config: dict, fallback: QdrantConfig) -> QdrantConfig:
    raw = user_config.get("qdrant")
    if not raw:
        return fallback
    try:
        return QdrantConfig(**raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prdoc_qdrant_config_invalid", error=str(exc))
        return fallback


async def process_prdoc_task(env: PRDocWorkerEnv, task_info: dict) -> None:
    if not env._initialized:
        raise RuntimeError("Worker not initialized")

    generation_id = UUID(task_info["generation_id"])
    config_key = task_info.get("config_key") or f"config:prdoc:{generation_id}"
    repo_id = task_info.get("repo_id")
    base_sha = task_info.get("base_sha")
    head_sha = task_info.get("head_sha")
    title = task_info.get("title")
    description = task_info.get("description")
    changed_files = task_info.get("changed_files") or []

    stream = _events_stream(generation_id)
    emitter = _make_event_emitter(env.redis, stream)

    log_id = f"prdoc:{generation_id}"
    bind_generation_context(log_id, env.redis)
    bind_pipeline(PRDOC.id)
    bind_phase("running")

    logger.info(
        "processing_prdoc_task",
        generation_id=str(generation_id),
        repo_id=repo_id,
        files_changed=len(changed_files),
    )

    try:
        user_config = await _load_user_config(env.redis, env.encryption, config_key)
        llm_cfg = LLMConfig(**user_config["llm"])
        embeddings_cfg = _resolve_embeddings(user_config)
        qdrant_cfg = _resolve_qdrant(user_config, env.config.qdrant)

        await env.prdoc_storage.mark_running(generation_id)
        await emitter(
            "prdoc.running",
            {
                "generation_id": str(generation_id),
                "files_changed": len(changed_files),
                "repo_id": repo_id,
            },
        )

        rag_snippets = await prdoc_service.fetch_rag_context(
            embeddings_cfg=embeddings_cfg,
            qdrant_cfg=qdrant_cfg,
            repo_id=repo_id,
            changed_files=changed_files,
        )
        if rag_snippets:
            logger.info(
                "prdoc_rag_context_attached",
                files_with_snippets=len(rag_snippets),
                total_snippets=sum(len(v) for v in rag_snippets.values()),
            )

        summary = await prdoc_service.run_prdoc_agent(
            llm_config=llm_cfg,
            title=title,
            description=description,
            base_sha=base_sha,
            head_sha=head_sha,
            changed_files=changed_files,
            rag_snippets_by_file=rag_snippets or None,
        )

        await env.prdoc_storage.mark_completed(
            generation_id=generation_id,
            summary=summary.summary_markdown,
            highlights=list(summary.highlights),
            concerns=list(summary.concerns),
            files_summarised=int(summary.files_summarised),
        )
        await emitter(
            "prdoc.completed",
            {
                "generation_id": str(generation_id),
                "files_summarised": int(summary.files_summarised),
                "highlights_count": len(summary.highlights),
                "concerns_count": len(summary.concerns),
            },
        )
        await env.redis.delete(config_key)

        logger.info(
            "prdoc_task_completed",
            generation_id=str(generation_id),
            files_summarised=int(summary.files_summarised),
        )

    except Exception as exc:
        logger.exception(
            "prdoc_task_failed",
            generation_id=str(generation_id),
            error=str(exc),
        )
        try:
            await env.prdoc_storage.mark_failed(generation_id, str(exc))
            await emitter(
                "prdoc.failed",
                {
                    "generation_id": str(generation_id),
                    "error": str(exc) or type(exc).__name__,
                    "error_type": type(exc).__name__,
                },
            )
        except Exception as inner:  # noqa: BLE001
            logger.error("prdoc_failure_record_error", error=str(inner))
        raise
    finally:
        clear_generation_context()
