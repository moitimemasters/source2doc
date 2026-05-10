import json
import typing as tp

import redis.asyncio as aioredis

from source2doc import config
from source2doc.events.bus import annotate_event
from source2doc.logging import get_logger
from source2doc.pipelines import DOCGEN

from worker.config import GatewayWorkerConfig
from worker.docgen.service import state as state_mod
from worker.encryption import ConfigEncryption
from worker.streams import consumer as consumer_mod


logger = get_logger(__name__)

ACTIVE_STREAMS_SET = "active_event_streams"


async def process_task_message(
    redis: aioredis.Redis,
    encryption: ConfigEncryption,
    worker_config: GatewayWorkerConfig,
    message: consumer_mod.StreamMessage,
) -> None:
    generation_id = message.data.get("generation_id")
    config_key = message.data.get("config_key")
    # ``trace_id`` is bound on contextvars by ``dispatch_message`` already;
    # we re-read here so we can stamp it on the first ``generation.requested``
    # event payload, which is the seed every event handler restarts from.
    trace_id = consumer_mod.trace_id_from_context()

    if not generation_id or not config_key:
        logger.error("invalid_task_message", data=message.data)
        return

    logger.info("processing_task", generation_id=generation_id)

    encrypted_config = await redis.get(config_key)
    if not encrypted_config:
        logger.error("config_not_found", generation_id=generation_id, config_key=config_key)
        return

    user_config = encryption.decrypt_config(encrypted_config)

    config_hash_key = f"config:docgen:{generation_id}"
    await _save_config_to_redis(redis, config_hash_key, user_config)

    output_language = (user_config.get("generation") or {}).get("output_language") or "en"
    await state_mod.create_state(
        redis,
        generation_id,
        worker_config.worker_id,
        output_language=output_language,
    )

    event_stream = f"{worker_config.redis.stream_prefix}:{generation_id}"
    await consumer_mod.ensure_consumer_group(redis, event_stream, "docgen-processors")

    await redis.sadd(ACTIVE_STREAMS_SET, event_stream)

    repo_id = user_config.get("repo_id")
    repo_path = user_config.get("repo_url")

    event_data: dict[str, tp.Any] = {"generation_id": generation_id}
    if trace_id:
        event_data["trace_id"] = trace_id
    if repo_id:
        event_data["repo_id"] = repo_id
    elif repo_path:
        event_data["path"] = repo_path
    else:
        logger.error("no_repo_source", generation_id=generation_id)
        return

    if user_config.get("name"):
        event_data["name"] = user_config["name"]
    if user_config.get("description"):
        event_data["description"] = user_config["description"]
    # B2.4 — opt-in full reindex flag. Lives in user_config so it survives
    # the encrypt → store → decrypt round-trip; the stream-level copy on
    # ``message.data`` is only used by the gateway for tracing.
    if user_config.get("force_reindex"):
        event_data["force_reindex"] = True
    # Iterative-mode envelope: gateway stamps this on the encrypted user
    # config when ``POST /api/v1/tasks/incremental`` is called. The
    # ingest handler forwards it untouched, the index handler uses it to
    # emit ``iterative.index_completed`` instead of ``index.completed``,
    # and the iterative orchestrator handler consumes it.
    if user_config.get("iterative"):
        event_data["iterative"] = user_config["iterative"]

    await consumer_mod.emit_to_stream(
        redis,
        event_stream,
        "generation.requested",
        annotate_event(DOCGEN, "generation.requested", event_data, logger),
    )

    logger.info(
        "task_initialized",
        generation_id=generation_id,
        event_stream=event_stream,
    )


async def _save_config_to_redis(
    redis: aioredis.Redis,
    key: str,
    user_config: dict,
    ttl_seconds: int = 86400,
) -> None:
    data = {
        "llm": json.dumps(user_config.get("llm", {})),
        "agents": json.dumps(user_config.get("agents", {})),
        "embeddings": json.dumps(user_config.get("embeddings", {})),
        "qdrant": json.dumps(user_config.get("qdrant", {})),
        "postgres": json.dumps(user_config.get("postgres", {})),
        "generation": json.dumps(user_config.get("generation", {})),
        "repo_id": user_config.get("repo_id") or "",
        "repo_url": user_config.get("repo_url") or "",
        "name": user_config.get("name") or "",
        "description": user_config.get("description") or "",
        # B2.4 — sticky on resume. Stored as "1"/"" for cheap truthiness.
        "force_reindex": "1" if user_config.get("force_reindex") else "",
    }
    await redis.hset(key, mapping=data)
    await redis.expire(key, ttl_seconds)


async def load_config_from_redis(
    redis: aioredis.Redis,
    generation_id: str,
) -> dict[str, tp.Any] | None:
    key = f"config:docgen:{generation_id}"
    data = await redis.hgetall(key)

    if not data:
        return None

    return {
        "llm": json.loads(data.get("llm", "{}")),
        "agents": json.loads(data.get("agents", "{}")),
        "embeddings": json.loads(data.get("embeddings", "{}")),
        "qdrant": json.loads(data.get("qdrant", "{}")),
        "postgres": json.loads(data.get("postgres", "{}")),
        "generation": json.loads(data.get("generation", "{}")),
        "repo_id": data.get("repo_id", ""),
        "repo_url": data.get("repo_url", ""),
        "name": data.get("name", "") or None,
        "description": data.get("description", "") or None,
    }


def build_app_config(
    worker_config: GatewayWorkerConfig,
    user_config: dict,
) -> config.AppConfig:
    postgres = worker_config.postgres

    agents_block = user_config.get("agents") or {}
    return config.AppConfig(
        llm=user_config["llm"],
        agents=agents_block,
        embeddings=user_config["embeddings"],
        qdrant=user_config["qdrant"],
        postgres=postgres,
        redis=config.RedisConfig(
            url=worker_config.redis.url,
            stream_prefix=worker_config.redis.stream_prefix,
            consumer_group=worker_config.redis.consumer_group,
            consumer_name=worker_config.worker_id,
            block_timeout_ms=worker_config.redis.block_timeout_ms,
            max_idle_time_ms=worker_config.redis.max_idle_time_ms,
            stream_ttl_seconds=worker_config.redis.stream_ttl_seconds,
        ),
        generation=user_config.get("generation", {}),
        prompts=config.PromptsConfig(
            planner=str(worker_config.prompts_dir / "planner.yaml"),
            subplanner=str(worker_config.prompts_dir / "subplanner.yaml"),
            writer=str(worker_config.prompts_dir / "writer.yaml"),
            critic=str(worker_config.prompts_dir / "critic.yaml"),
            diagrammer=str(worker_config.prompts_dir / "diagrammer.yaml"),
            normalizer=str(worker_config.prompts_dir / "normalizer.yaml"),
        ),
        logging=config.LoggingConfig(level="INFO"),
        logfire=worker_config.logfire,
    )


async def cleanup_generation(
    redis: aioredis.Redis,
    generation_id: str,
    stream_prefix: str,
) -> None:
    event_stream = f"{stream_prefix}:{generation_id}"
    # Drop the active-set membership so /streams "Active" count goes to 0,
    # but keep the event stream itself around so the user can still browse
    # the run on /streams and /streams/{id}/logs after completion. The
    # stream's per-key TTL (set on every XADD) handles eventual eviction.
    await redis.srem(ACTIVE_STREAMS_SET, event_stream)

    config_key = f"config:docgen:{generation_id}"
    await redis.delete(config_key)

    await state_mod.delete_state(redis, generation_id)

    logger.info("generation_cleaned_up", generation_id=generation_id)
