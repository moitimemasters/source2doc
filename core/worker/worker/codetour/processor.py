import datetime as dt
import json
from pathlib import Path
from uuid import UUID

from source2doc import errors as errors_lib
from source2doc import get_logger
from source2doc.config import EmbeddingsConfig, GenerationConfig, LLMConfig, QdrantConfig
from source2doc.events.bus import annotate_event
from source2doc.git_context import GitContext
from source2doc.logging import (
    bind_generation_context,
    bind_phase,
    bind_pipeline,
    clear_generation_context,
)
from source2doc.pipelines import CODETOUR
from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import S3FileSystem

from docgen_core.services.embeddings.openai import OpenAIEmbeddings
from docgen_core.services.vectorstore.qdrant import QdrantVectorStore

import codetour_core
from codetour_core import followup as codetour_followup
from codetour_core import generator as codetour_generator
from codetour_core import models as codetour_models

from worker.codetour.env import CodetourWorkerEnv
from worker.streams import consumer as consumer_mod


logger = get_logger(__name__)


CONFIG_TTL_SECONDS = 24 * 3600
TOUR_EVENTS_TTL_SECONDS = 24 * 3600


def _resolve_codetour_prompt_path(configured_dir: Path) -> Path:
    """The shared worker config points ``prompts_dir`` at the docgen prompts
    by default. The codetour prompt lives in the codetour package, so we look
    there first and fall back to ``configured_dir``."""

    candidates: list[Path] = []
    package_dir = Path(codetour_core.__file__).resolve().parent.parent
    candidates.append(package_dir / "configs" / "agents" / "codetour_generator.yaml")
    candidates.append(configured_dir / "codetour_generator.yaml")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"codetour_generator.yaml not found. Tried: {[str(c) for c in candidates]}"
    )


async def _lookup_repo_id_for_generation(storage, generation_id: UUID) -> str | None:
    """Find the bundle's repo_id by generation_id. Returns the UUID as a string
    suitable for ``S3FileSystem(repo_id=...)`` or ``None`` if the bundle has no
    repo attached."""
    if storage.pool is None:
        return None
    async with storage.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT repo_id FROM documentation_bundles WHERE generation_id = $1",
            generation_id,
        )
    if not row or not row["repo_id"]:
        return None
    return str(row["repo_id"])


async def _load_user_config(
    redis,
    encryption: ConfigEncryption,
    config_key: str,
) -> dict:
    encrypted = await redis.get(config_key)
    if not encrypted:
        raise RuntimeError(
            f"Encrypted codetour config not found at {config_key} (cancelled or TTL expired?)"
        )
    return encryption.decrypt_config(encrypted)


def _events_stream(tour_id: UUID) -> str:
    return f"events:codetour:{tour_id}"


def _make_event_emitter(redis, stream: str):
    async def emit(event_type: str, data: dict) -> None:
        # Stamp the trace_id from contextvars so each emitted event keeps
        # the correlation token threaded through follow-up handlers.
        payload = dict(data)
        trace_id = consumer_mod.trace_id_from_context()
        if trace_id and "trace_id" not in payload:
            payload["trace_id"] = trace_id
        annotated = annotate_event(CODETOUR, event_type, payload, logger)
        await redis.xadd(stream, {"type": event_type, "data": json.dumps(annotated)})
        await redis.expire(stream, TOUR_EVENTS_TTL_SECONDS)

    return emit


def _resolve_embeddings_config(user_config: dict) -> EmbeddingsConfig:
    raw = user_config.get("embeddings")
    if not raw:
        raise ValueError(
            "embeddings config is required: an LLM endpoint cannot be reused "
            "as an embeddings endpoint. Pass `embeddings.{provider, model, "
            "api_key, base_url, dimensions}` in the request payload."
        )
    return EmbeddingsConfig(**raw)


def _resolve_qdrant_config(
    user_config: dict,
    fallback: QdrantConfig,
    collection: str,
) -> QdrantConfig:
    raw = user_config.get("qdrant")
    base = QdrantConfig(**raw) if raw else fallback
    return base.model_copy(update={"collection": collection})


async def _run_generator(
    env: CodetourWorkerEnv,
    request: codetour_models.CodeTourGenerationRequest,
    user_config: dict,
    repo_id: str | None,
    emitter,
) -> codetour_models.CodeTour:
    """Build the generator pipeline and run it. Extracted so tests can replace
    this single coroutine with an AsyncMock."""

    embeddings_cfg = _resolve_embeddings_config(user_config)
    qdrant_cfg = _resolve_qdrant_config(user_config, env.config.qdrant, request.qdrant_collection)
    llm_cfg = LLMConfig(**user_config["llm"])

    embeddings = OpenAIEmbeddings(embeddings_cfg)
    vectorstore = QdrantVectorStore(qdrant_cfg, embeddings_cfg.dimensions)

    filesystem = None
    git_context = None
    if repo_id and env.config.s3:
        filesystem = S3FileSystem(env.config.s3, repo_id)
        # Trigger extraction so we know the on-disk path before passing it to git.
        try:
            base_path = await filesystem._ensure_extracted()
            git_context = GitContext(base_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "git_context_init_failed",
                repo_id=repo_id,
                error=str(exc),
            )

    prompt_path = _resolve_codetour_prompt_path(env.config.prompts_dir)

    gen = codetour_generator.CodetourGenerator(
        llm_config=llm_cfg,
        embeddings=embeddings,
        vectorstore=vectorstore,
        storage=env.codetour_storage,
        prompt_path=prompt_path,
        generation_config=GenerationConfig(),
        filesystem=filesystem,
        event_emitter=emitter,
        git_context=git_context,
    )
    return await gen.generate(request)


async def process_codetour_task(env: CodetourWorkerEnv, task_info: dict) -> None:
    if not env._initialized:
        raise RuntimeError("Worker not initialized")

    kind = task_info.get("kind", "initial")
    if kind == "followup":
        await _process_followup_task(env, task_info)
        return

    tour_id = UUID(task_info["tour_id"])
    generation_id = UUID(task_info["generation_id"])
    query = task_info["query"]
    max_steps = task_info.get("max_steps", 10)
    repo_id = task_info.get("repo_id")
    config_key = task_info.get("config_key") or f"config:codetour:{tour_id}"
    qdrant_collection = (
        task_info.get("qdrant_collection") or f"docgen_{generation_id}"
    )

    # Fall back to the bundle's repo_id if the request didn't carry one — that
    # way the agent gets a real filesystem and can read source files even when
    # the user just typed a query and a generation_id.
    if not repo_id and env.storage is not None:
        try:
            repo_id = await _lookup_repo_id_for_generation(env.storage, generation_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "codetour_repo_lookup_failed",
                generation_id=str(generation_id),
                error=str(exc),
            )

    stream = _events_stream(tour_id)
    emitter = _make_event_emitter(env.redis, stream)

    # Match the stream id format used by the gateway (codetour:{tour_id}) so
    # logs:codetour:{tour_id} pairs with events:codetour:{tour_id} and the UI
    # /streams/<id>/logs route resolves to the right key.
    log_id = f"codetour:{tour_id}"
    bind_generation_context(log_id, env.redis)
    bind_pipeline(CODETOUR.id)
    bind_phase("running")

    logger.info(
        "processing_codetour_task",
        tour_id=str(tour_id),
        generation_id=str(generation_id),
        query=query,
        repo_id=repo_id,
        max_steps=max_steps,
    )

    try:
        user_config = await _load_user_config(env.redis, env.encryption, config_key)

        await env.codetour_storage.mark_running(tour_id)
        await emitter(
            "codetour.started",
            {
                "tour_id": str(tour_id),
                "generation_id": str(generation_id),
                "query": query,
            },
        )

        request = codetour_models.CodeTourGenerationRequest(
            tour_id=tour_id,
            query=query,
            generation_id=generation_id,
            qdrant_collection=qdrant_collection,
            max_steps=max_steps,
            mode=task_info.get("mode", "overview"),
        )

        tour = await _run_generator(env, request, user_config, repo_id, emitter)

        if not tour.steps:
            raise RuntimeError(
                "codetour generator returned 0 steps — agent could not "
                "find usable code for the query"
            )

        await env.codetour_storage.mark_completed(
            tour_id=tour.tour_id,
            title=tour.title,
            description=tour.description,
            steps=[step.model_dump() for step in tour.steps],
            metadata=tour.metadata,
        )
        await emitter(
            "codetour.completed",
            {
                "tour_id": str(tour.tour_id),
                "steps_count": len(tour.steps),
            },
        )
        await env.redis.delete(config_key)

        logger.info(
            "codetour_task_completed",
            tour_id=str(tour_id),
            steps=len(tour.steps),
        )

    except Exception as exc:
        logger.exception(
            "codetour_task_failed",
            tour_id=str(tour_id),
            error=str(exc),
        )
        try:
            await env.codetour_storage.mark_failed(tour_id, str(exc))
            failure_payload = _build_failure_payload(tour_id, exc)
            await emitter("codetour.failed", failure_payload)
        except Exception as inner:  # noqa: BLE001
            logger.error("codetour_failure_record_error", error=str(inner))
        raise
    finally:
        clear_generation_context()


def _build_failure_payload(tour_id: UUID, exc: BaseException) -> dict:
    """Common failure payload + LLM-timeout enrichment.

    Mirrors ``_emit_step_failed`` in docgen so the UI can use the same
    ``reason='llm_timeout'`` branch for both pipelines.
    """

    payload: dict = {
        "tour_id": str(tour_id),
        "error": str(exc),
        "error_type": type(exc).__name__,
    }
    if isinstance(exc, errors_lib.LLMTimeoutError):
        payload["reason"] = "llm_timeout"
        payload["error_message"] = (
            f"LLM call timed out after {exc.last_attempt_n} attempts ({exc.elapsed_s:.1f} s total)"
        )
        payload["model"] = exc.model
        payload["elapsed_s"] = exc.elapsed_s
        payload["last_attempt_n"] = exc.last_attempt_n
        payload["retry_after"] = None
    return payload


async def _process_followup_task(env: CodetourWorkerEnv, task_info: dict) -> None:
    tour_id = UUID(task_info["tour_id"])
    request_id = UUID(task_info["request_id"])
    step_index = int(task_info["step_index"])
    question = task_info["question"]
    max_new_steps = int(task_info.get("max_new_steps", 3))
    config_key = task_info["config_key"]

    stream = _events_stream(tour_id)
    emitter = _make_event_emitter(env.redis, stream)

    log_id = f"codetour:{tour_id}"
    bind_generation_context(log_id, env.redis)
    bind_pipeline(CODETOUR.id)
    bind_phase("followup")

    logger.info(
        "processing_codetour_followup_task",
        tour_id=str(tour_id),
        request_id=str(request_id),
        step_index=step_index,
    )

    try:
        tour_row = await env.codetour_storage.get_codetour(tour_id)
        if not tour_row:
            raise RuntimeError(f"Tour {tour_id} not found")

        tour = codetour_models.CodeTour(
            tour_id=tour_id,
            generation_id=UUID(tour_row["generation_id"]),
            title=tour_row["title"] or "",
            description=tour_row["description"] or "",
            steps=[codetour_models.CodeTourStep(**s) for s in (tour_row["steps"] or [])],
            created_at=dt.datetime.fromisoformat(tour_row["created_at"])
            if isinstance(tour_row["created_at"], str)
            else dt.datetime.now(dt.UTC),
            metadata=tour_row.get("metadata") or {},
        )

        user_config = await _load_user_config(env.redis, env.encryption, config_key)

        request = codetour_models.CodeTourFollowupRequest(
            tour_id=tour_id,
            step_index=step_index,
            question=question,
            qdrant_collection=tour.metadata.get(
                "qdrant_collection",
                f"docgen_{tour.generation_id}",
            ),
            max_new_steps=max_new_steps,
        )

        embeddings_cfg = _resolve_embeddings_config(user_config)
        qdrant_cfg = _resolve_qdrant_config(
            user_config, env.config.qdrant, request.qdrant_collection
        )
        from source2doc.config import LLMConfig as _LLM
        llm_cfg = _LLM(**user_config["llm"])

        embeddings = OpenAIEmbeddings(embeddings_cfg)
        vectorstore = QdrantVectorStore(qdrant_cfg, embeddings_cfg.dimensions)

        filesystem = None
        git_context = None
        repo_id = (tour.metadata or {}).get("repo_id") or tour_row.get(
            "request_payload", {}
        ).get("repo_id")
        if not repo_id and env.storage is not None:
            try:
                repo_id = await _lookup_repo_id_for_generation(
                    env.storage, tour.generation_id
                )
            except Exception:  # noqa: BLE001
                repo_id = None
        if repo_id and env.config.s3:
            from source2doc.storage import S3FileSystem as _S3FS
            filesystem = _S3FS(env.config.s3, repo_id)
            try:
                base_path = await filesystem._ensure_extracted()
                git_context = GitContext(base_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "git_context_init_failed",
                    repo_id=repo_id,
                    error=str(exc),
                )

        prompt_path = _resolve_codetour_prompt_path(env.config.prompts_dir)

        await emitter(
            "codetour.followup_started",
            {
                "tour_id": str(tour_id),
                "request_id": str(request_id),
                "step_index": step_index,
            },
        )

        new_steps = await codetour_followup.generate_followup(
            tour,
            request,
            llm_config=llm_cfg,
            embeddings=embeddings,
            vectorstore=vectorstore,
            generation_config=__import__("source2doc.config", fromlist=["GenerationConfig"]).GenerationConfig(),
            prompt_path=prompt_path,
            filesystem=filesystem,
            event_emitter=emitter,
            git_context=git_context,
        )

        await env.codetour_storage.append_followup_steps(
            tour_id, [s.model_dump() for s in new_steps]
        )
        await emitter(
            "codetour.followup_completed",
            {
                "tour_id": str(tour_id),
                "request_id": str(request_id),
                "appended": len(new_steps),
            },
        )
        await env.redis.delete(config_key)

        logger.info(
            "codetour_followup_task_completed",
            tour_id=str(tour_id),
            appended=len(new_steps),
        )

    except Exception as exc:
        logger.exception(
            "codetour_followup_task_failed",
            tour_id=str(tour_id),
            error=str(exc),
        )
        try:
            payload = _build_failure_payload(tour_id, exc)
            payload["request_id"] = str(request_id)
            await emitter("codetour.followup_failed", payload)
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        clear_generation_context()
