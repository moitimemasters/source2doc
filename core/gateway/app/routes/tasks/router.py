from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis

from source2doc import storage as storage_lib
from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.presets import ConfigPresetStorage

from app import config as app_config
from app.routes.admin.presets.dependencies import get_preset_storage
from app.routes.codetours.dependencies import get_encryption
from app.routes.docs import dependencies as docs_deps
from app.routes.streams import dependencies as streams_deps
from app.routes.tasks import dto as tasks_dto
from app.routes.tasks import service as tasks_service
from app.security.admin import require_admin


router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_admin)],
)


@router.post("", response_model=tasks_dto.TaskResponse)
async def create_task_route(
    request: tasks_dto.TaskRequest,
    redis: aioredis.Redis = Depends(streams_deps.get_redis),
    config: app_config.Config = Depends(app_config.get_config),
    storage: storage_lib.PostgresStorage = Depends(docs_deps.get_storage),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
    encryption: ConfigEncryption = Depends(get_encryption),
) -> tasks_dto.TaskResponse:
    return await tasks_service.create_task(
        request, config, redis, storage, presets, encryption
    )


@router.post("/incremental", response_model=tasks_dto.IterativeTaskResponse)
async def create_iterative_task_route(
    request: tasks_dto.IterativeTaskRequest,
    redis: aioredis.Redis = Depends(streams_deps.get_redis),
    config: app_config.Config = Depends(app_config.get_config),
    storage: storage_lib.PostgresStorage = Depends(docs_deps.get_storage),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
    encryption: ConfigEncryption = Depends(get_encryption),
) -> tasks_dto.IterativeTaskResponse:
    """Iterative-mode docgen.

    Reuses the previous bundle's pages where possible: only pages whose
    ``source_files`` overlap ``changed_files`` are re-written by the
    writer (in update-mode), pages whose source files are entirely in
    ``deleted_files`` are copied with ``deprecated=TRUE``, and changed
    files not covered by any prior page get fresh pages via the
    heuristic orphan planner. Skips the LLM-heavy planner/subplanner
    phases; ingest+index still run (B2.4 incremental cache applies).
    """

    try:
        return await tasks_service.create_iterative_task(
            request, config, redis, storage, presets, encryption
        )
    except ValueError as exc:
        # Validation failures from base-bundle resolution surface as 422
        # so the UI can render the message verbatim instead of generic
        # 500-internal noise.
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{generation_id}", response_model=tasks_dto.TaskStatusResponse)
async def get_task_status_route(
    generation_id: UUID,
    redis: aioredis.Redis = Depends(streams_deps.get_redis),
    storage: storage_lib.PostgresStorage = Depends(docs_deps.get_storage),
) -> tasks_dto.TaskStatusResponse:
    status = await tasks_service.get_task_status(generation_id, redis, storage)
    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task {generation_id} not found",
        )
    return status
