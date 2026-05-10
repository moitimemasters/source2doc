from uuid import UUID

from fastapi import APIRouter, Depends
import redis.asyncio as aioredis

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import codetour as codetour_storage
from source2doc.storage.presets import ConfigPresetStorage

from app.routes.admin.presets.dependencies import get_preset_storage
from app.routes.codetours import service
from app.routes.codetours.dependencies import get_codetour_storage, get_encryption
from app.routes.codetours.dto import (
    AdminCodetourFollowupRequest,
    AdminCodetourRequest,
    CodetourFollowupResponse,
    CodetourResponse,
)
from app.routes.streams.dependencies import get_redis
from app.security.admin import require_admin


router = APIRouter(
    prefix="/api/v1/admin/codetours",
    tags=["admin:codetours"],
    dependencies=[Depends(require_admin)],
)


@router.post("", response_model=CodetourResponse)
async def admin_create_codetour_route(
    request: AdminCodetourRequest,
    redis: aioredis.Redis = Depends(get_redis),
    encryption: ConfigEncryption = Depends(get_encryption),
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> CodetourResponse:
    return await service.create_codetour(request, redis, encryption, storage, presets)


@router.post("/{tour_id}/followup", response_model=CodetourFollowupResponse)
async def admin_followup_codetour_route(
    tour_id: UUID,
    request: AdminCodetourFollowupRequest,
    redis: aioredis.Redis = Depends(get_redis),
    encryption: ConfigEncryption = Depends(get_encryption),
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> CodetourFollowupResponse:
    return await service.request_followup(
        tour_id, request, redis, encryption, storage, presets
    )
