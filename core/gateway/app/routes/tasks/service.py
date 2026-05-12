import json
import uuid
from uuid import UUID, uuid4

import redis.asyncio as aioredis
import structlog
from fastapi import HTTPException

from source2doc import storage as storage_lib
from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.presets import ConfigPresetStorage

from app import config as app_config
from app.routes._shared.preset_resolver import resolve_configs
from app.routes.tasks import dto as tasks_dto


TASKS_STREAM = "tasks:docgen"
TASKS_CONSUMER_GROUP = "docgen-receivers"


def _set_logfire_trace_attribute(trace_id: str) -> None:
    """Best-effort tag the active logfire span with our trace_id.

    Falls through silently when logfire is not installed or no span is
    active — trace propagation must never break a normal request flow.
    """
    try:
        import logfire

        logfire.current_span().set_attribute("trace_id", trace_id)
    except Exception:  # noqa: BLE001
        pass


async def create_task(
    request: tasks_dto.TaskRequest,
    config: app_config.Config,
    redis: aioredis.Redis,
    storage: storage_lib.PostgresStorage,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> tasks_dto.TaskResponse:
    generation_id = uuid4()
    trace_id = uuid.uuid4().hex
    qdrant_collection = f"docgen_{generation_id}"

    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        generation_id=str(generation_id),
    )
    _set_logfire_trace_attribute(trace_id)

    try:
        # Gate on repo readiness: until the repos worker finishes the clone +
        # S3 upload, `s3_key` is NULL. Kicking off docgen before then fails
        # downstream with a confusing "Repository not found" from S3, so
        # reject here with a clear message instead.
        repo = await storage.get_repository(UUID(request.repo_id))
        if repo is None:
            raise HTTPException(
                status_code=404,
                detail=f"Repository not found: {request.repo_id}",
            )
        if not repo.s3_key:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Repository is still being cloned. Wait for the clone to "
                    "finish (status will turn ready) and try again."
                ),
            )

        task_name = request.name or repo.name or f"Documentation for {request.repo_id[:8]}"

        resolved = await resolve_configs(
            request_llm=request.llm,
            request_embeddings=request.embeddings,
            request_qdrant=request.qdrant,
            preset_name=request.preset,
            presets=presets,
            encryption=encryption,
        )

        user_config = _build_user_config(
            request,
            config,
            generation_id,
            qdrant_collection,
            task_name,
            request.description,
            resolved,
        )

        encrypted_config = encryption.encrypt_config(user_config)

        config_key = f"config:{generation_id}"
        await redis.setex(config_key, 86400, encrypted_config)

        await _ensure_consumer_group(redis, TASKS_STREAM, TASKS_CONSUMER_GROUP)

        await redis.xadd(
            TASKS_STREAM,
            {
                "type": "task.created",
                "data": json.dumps(
                    {
                        "generation_id": str(generation_id),
                        "trace_id": trace_id,
                        "config_key": config_key,
                        "qdrant_collection": qdrant_collection,
                        "name": task_name,
                        # B2.4 — propagate the per-task incremental flag so
                        # the docgen worker's ingest handler can read it
                        # off the stream entry without decrypting the
                        # config blob.
                        "force_reindex": request.force_reindex,
                    }
                ),
            },
        )

        return tasks_dto.TaskResponse(
            generation_id=generation_id,
            name=task_name,
            trace_id=trace_id,
            status="pending",
            message="Task created successfully. Workers will process it shortly.",
            stream_url=f"/api/v1/streams/{generation_id}/stream",
            events_url=f"/api/v1/streams/{generation_id}/events",
        )
    finally:
        structlog.contextvars.clear_contextvars()


def _build_user_config(
    request: tasks_dto.TaskRequest,
    config: app_config.Config,
    generation_id: UUID,
    qdrant_collection: str,
    name: str | None,
    description: str | None,
    resolved: dict,
) -> dict:
    qdrant_block = resolved.get("qdrant") or {}
    qdrant_url = qdrant_block.get("url") or config.qdrant.url
    qdrant_api_key = qdrant_block.get("api_key") or config.qdrant.api_key
    user_config: dict = {
        "generation_id": str(generation_id),
        "repo_id": request.repo_id,
        "name": name,
        "description": description,
        "llm": resolved["llm"],
        "embeddings": resolved["embeddings"],
        "qdrant": {
            "url": qdrant_url,
            "collection": qdrant_collection,
            "api_key": qdrant_api_key,
        },
        "postgres": {
            "connection_string": config.postgres.connection_string,
        },
        "generation": request.generation.model_dump(),
        # B2.4 — sticky per-task flag. Mirrors the value stamped on the
        # Redis-stream entry so a config-only handler (e.g. the ingest
        # handler reading the encrypted blob) can still see it.
        "force_reindex": request.force_reindex,
    }
    agents = resolved.get("agents")
    if agents:
        user_config["agents"] = agents
    return user_config


async def create_iterative_task(
    request: tasks_dto.IterativeTaskRequest,
    config: app_config.Config,
    redis: aioredis.Redis,
    storage: storage_lib.PostgresStorage,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> tasks_dto.IterativeTaskResponse:
    """Mirrors :func:`create_task` but records an iterative-mode envelope
    on the encrypted user config so the worker dispatches into the
    incremental orchestrator path (skipping planner/subplanner) once
    ingest+index complete.

    Resolves ``base_generation_id`` from the latest bundle for the repo
    when omitted; validates that the resolved base belongs to the repo
    so a misclick can't accidentally rebase one repo's docs onto another's
    bundle.
    """

    repo_uuid = UUID(request.repo_id)

    # See ``create_task``: reject before queuing if the clone hasn't
    # finished, otherwise docgen fails midway with a confusing S3 error.
    repo = await storage.get_repository(repo_uuid)
    if repo is None:
        raise HTTPException(
            status_code=404, detail=f"Repository not found: {request.repo_id}"
        )
    if not repo.s3_key:
        raise HTTPException(
            status_code=409,
            detail=(
                "Repository is still being cloned. Wait for the clone to "
                "finish and try again."
            ),
        )

    # Validate that the caller gave us *something* the worker can turn
    # into a (changed, deleted) pair. The handler accepts either an
    # explicit list or a commit range — but not neither, because that
    # would yield a no-op iterative bundle (every page unchanged) which
    # is almost never what the caller meant.
    has_files = bool(request.changed_files) or bool(request.deleted_files)
    has_range = bool(request.from_commit and request.to_commit)
    if not has_files and not has_range:
        raise ValueError(
            "iterative request must specify either ``changed_files`` (and/or "
            "``deleted_files``), or both ``from_commit`` and ``to_commit``"
        )

    # Resolve the base bundle — either explicit or latest-for-repo. We
    # fetch it eagerly so we can sanity-check ownership before queuing
    # any work.
    if request.base_generation_id:
        base_uuid = UUID(request.base_generation_id)
        base_bundle = await storage.get_bundle(base_uuid)
        if base_bundle is None:
            raise ValueError(
                f"base_generation_id {request.base_generation_id} not found"
            )
        if base_bundle.get("repo_id") != str(repo_uuid):
            raise ValueError(
                "base_generation_id belongs to a different repository "
                f"({base_bundle.get('repo_id')!r}); refusing to derive iterative bundle"
            )
        base_generation_id = str(base_uuid)
    else:
        latest = await storage.latest_bundle_for_repo(repo_uuid)
        if latest is None:
            raise ValueError(
                "no existing bundle for this repo — iterative mode requires a base"
            )
        base_generation_id = latest["generation_id"]

    generation_id = uuid4()
    trace_id = uuid.uuid4().hex
    qdrant_collection = f"docgen_{generation_id}"

    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        generation_id=str(generation_id),
    )
    _set_logfire_trace_attribute(trace_id)

    try:
        task_name = request.name
        if not task_name:
            base_label = base_generation_id[:8]
            task_name = (
                f"Iterative update of {repo.name}" if repo else f"Iterative {base_label}"
            )

        resolved = await resolve_configs(
            request_llm=request.llm,
            request_embeddings=request.embeddings,
            request_qdrant=request.qdrant,
            preset_name=request.preset,
            presets=presets,
            encryption=encryption,
        )

        # The TaskRequest-shaped builder reads only fields ``request``
        # exposes that exist on both DTOs (repo_id, llm, embeddings,
        # qdrant, generation, force_reindex). Both DTOs satisfy that
        # surface, so we reuse ``_build_user_config`` rather than
        # cloning it.
        user_config = _build_user_config(
            request,
            config,
            generation_id,
            qdrant_collection,
            task_name,
            request.description,
            resolved,
        )
        # Stamp the iterative envelope onto the user config so the worker
        # processor can copy it into the first ``generation.requested``
        # event without decrypting twice. The orchestrator handler reads
        # ``base_generation_id``, ``changed_files``, ``deleted_files``
        # off this dict.
        user_config["iterative"] = {
            "base_generation_id": base_generation_id,
            "changed_files": list(request.changed_files),
            "deleted_files": list(request.deleted_files),
            # When ``from_commit`` + ``to_commit`` are both set the worker
            # populates ``changed_files``/``deleted_files`` itself by running
            # ``git diff --name-status`` against the unpacked repo. Lets the
            # caller (typically a CI pipeline) avoid client-side git parsing.
            "from_commit": request.from_commit,
            "to_commit": request.to_commit,
            "head_sha": request.head_sha or request.to_commit,
        }

        encrypted_config = encryption.encrypt_config(user_config)

        config_key = f"config:{generation_id}"
        await redis.setex(config_key, 86400, encrypted_config)

        await _ensure_consumer_group(redis, TASKS_STREAM, TASKS_CONSUMER_GROUP)

        await redis.xadd(
            TASKS_STREAM,
            {
                "type": "task.created",
                "data": json.dumps(
                    {
                        "generation_id": str(generation_id),
                        "trace_id": trace_id,
                        "config_key": config_key,
                        "qdrant_collection": qdrant_collection,
                        "name": task_name,
                        "force_reindex": request.force_reindex,
                        "mode": "incremental",
                        "base_generation_id": base_generation_id,
                    }
                ),
            },
        )

        return tasks_dto.IterativeTaskResponse(
            generation_id=generation_id,
            base_generation_id=base_generation_id,
            name=task_name,
            trace_id=trace_id,
            status="pending",
            message=(
                f"Iterative task created (base: {base_generation_id[:8]}…); "
                "workers will pick it up shortly."
            ),
            stream_url=f"/api/v1/streams/{generation_id}/stream",
            events_url=f"/api/v1/streams/{generation_id}/events",
        )
    finally:
        structlog.contextvars.clear_contextvars()


async def get_task_status(
    generation_id: UUID,
    redis: aioredis.Redis,
    storage: storage_lib.PostgresStorage,
) -> tasks_dto.TaskStatusResponse | None:
    """Derive task status from the per-generation Redis stream.

    Status is computed from the *terminal* event present in the stream:
    ``generation.completed`` → ``completed``, ``generation.failed`` /
    ``handler.error`` / ``step.failed`` → ``failed``. Otherwise — ``running``
    if the stream has any events, ``pending`` if the stream key is absent.

    Repository / bundle metadata is enriched from PostgreSQL.
    """

    stream_name = f"events:{generation_id}"

    # Fetch up to last 200 entries; that's enough to spot a terminal event
    # without dragging huge payloads of write-page events around.
    try:
        entries = await redis.xrevrange(stream_name, "+", "-", count=200)
    except aioredis.ResponseError:
        entries = []

    bundle = await storage.get_bundle(generation_id)

    if not entries and not bundle:
        return None

    # Default: derive from the stream. If the stream is already gone (post
    # `generation_cleaned_up`) but the bundle has pages — the run completed
    # successfully and the stream was archived. Treat that as `completed`.
    pages_count = 0
    if bundle:
        pages = await storage.get_bundle_pages(generation_id)
        pages_count = len(pages or [])

    status = "pending"
    if not entries and pages_count > 0:
        status = "completed"

    last_completed_step: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    if entries:
        # entries are newest-first
        terminal_failure_types = {
            "generation.failed",
            "handler.error",
            "step.failed",
        }
        for entry_id, fields in entries:
            etype = fields.get("type", "")
            if etype == "generation.completed":
                status = "completed"
                completed_at = _entry_id_to_iso(entry_id)
                break
            if etype in terminal_failure_types:
                status = "failed"
                completed_at = _entry_id_to_iso(entry_id)
                try:
                    payload = json.loads(fields.get("data", "{}"))
                    error_message = payload.get("error") or payload.get("error_message")
                except Exception:  # noqa: BLE001
                    pass
                break
        else:
            status = "running"

        # earliest entry → started_at; entries are newest-first, take the last.
        oldest_id = entries[-1][0]
        started_at = _entry_id_to_iso(oldest_id)

        # Find the most recent ``*.completed`` event as the last completed step.
        for _entry_id, fields in entries:
            etype = fields.get("type", "")
            if etype.endswith(".completed") and etype != "generation.completed":
                last_completed_step = etype.removesuffix(".completed")
                break

    repository_short: tasks_dto.RepositoryInfoShort | None = None
    bundle_name: str | None = None
    bundle_description: str | None = None
    repo_id_str: str | None = None
    created_at_iso: str = ""
    updated_at_iso: str = ""

    if bundle:
        bundle_name = bundle.get("name")
        bundle_description = bundle.get("description")
        repo_id_str = (
            str(bundle["repo_id"]) if bundle.get("repo_id") else None
        )
        created_at_iso = bundle.get("created_at") or ""
        updated_at_iso = bundle.get("updated_at") or created_at_iso
        if bundle.get("repo_name"):
            repository_short = tasks_dto.RepositoryInfoShort(
                name=bundle["repo_name"],
                source_type=bundle.get("repo_source_type") or "",
                git_url=bundle.get("repo_git_url"),
                git_branch=bundle.get("repo_git_branch"),
            )

    return tasks_dto.TaskStatusResponse(
        generation_id=str(generation_id),
        name=bundle_name,
        description=bundle_description,
        worker_id=None,
        status=status,
        repo_id=repo_id_str,
        repository=repository_short,
        started_at=started_at,
        completed_at=completed_at,
        error_message=error_message,
        retry_count=0,
        last_completed_step=last_completed_step,
        created_at=created_at_iso or (started_at or ""),
        updated_at=updated_at_iso or (completed_at or started_at or ""),
        steps=[],
    )


def _entry_id_to_iso(entry_id: str) -> str:
    """Redis stream IDs are ``<ms_ts>-<seq>``. Convert ``<ms_ts>`` to ISO."""
    import datetime as _dt

    try:
        ms = int(entry_id.split("-", 1)[0])
        return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.UTC).isoformat()
    except Exception:  # noqa: BLE001
        return ""


async def _ensure_consumer_group(
    redis: aioredis.Redis,
    stream_name: str,
    group_name: str,
) -> None:
    try:
        await redis.xgroup_create(
            name=stream_name,
            groupname=group_name,
            id="0",
            mkstream=True,
        )
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
