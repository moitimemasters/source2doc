from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import codetour as codetour_storage
from source2doc.storage.presets import ConfigPresetStorage

from app.routes._shared.sse import with_idle_pings
from app.routes.admin.presets.dependencies import get_preset_storage
from app.routes.codetours import service
from app.routes.codetours.dependencies import get_codetour_storage, get_encryption
from app.routes.codetours.dto import (
    CodetourDetail,
    CodetourFollowupRequest,
    CodetourFollowupResponse,
    CodetourListResponse,
    CodetourRequest,
    CodetourResponse,
)
from app.routes.streams.dependencies import get_redis


router = APIRouter(prefix="/api/v1/codetours", tags=["codetours"])


@router.post("", response_model=CodetourResponse)
async def create_codetour_route(
    request: CodetourRequest,
    redis: aioredis.Redis = Depends(get_redis),
    encryption: ConfigEncryption = Depends(get_encryption),
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> CodetourResponse:
    return await service.create_codetour(request, redis, encryption, storage, presets)


@router.post("/{tour_id}/cancel")
async def cancel_codetour_route(
    tour_id: UUID,
    redis: aioredis.Redis = Depends(get_redis),
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
) -> dict:
    await service.cancel_codetour(tour_id, redis, storage)
    return {"tour_id": str(tour_id), "status": "cancelled"}


@router.post("/{tour_id}/followup", response_model=CodetourFollowupResponse)
async def followup_codetour_route(
    tour_id: UUID,
    request: CodetourFollowupRequest,
    redis: aioredis.Redis = Depends(get_redis),
    encryption: ConfigEncryption = Depends(get_encryption),
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> CodetourFollowupResponse:
    return await service.request_followup(tour_id, request, redis, encryption, storage, presets)


@router.get("/{tour_id}/stream")
async def stream_codetour_events_route(
    tour_id: UUID,
    redis: aioredis.Redis = Depends(get_redis),
) -> StreamingResponse:
    return StreamingResponse(
        with_idle_pings(service.stream_tour_events(redis, tour_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/generation/{generation_id}", response_model=CodetourListResponse)
async def list_codetours_by_generation_route(
    generation_id: UUID,
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
) -> CodetourListResponse:
    tours = await service.list_codetours_by_generation(generation_id, storage)
    return CodetourListResponse(tours=tours)


@router.get("/{tour_id}", response_model=CodetourDetail)
async def get_codetour_route(
    tour_id: UUID,
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
) -> CodetourDetail:
    return await service.get_codetour(tour_id, storage)


@router.get("", response_model=CodetourListResponse)
async def list_all_codetours_route(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    storage: codetour_storage.CodetourStorage = Depends(get_codetour_storage),
) -> CodetourListResponse:
    tours = await service.list_all_codetours(storage, limit, offset)
    return CodetourListResponse(tours=tours)
