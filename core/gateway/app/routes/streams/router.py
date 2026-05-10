from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from source2doc.storage import PostgresStorage

from app.config import Config, get_config
from app.routes.streams import service
from app.routes.streams.dependencies import get_redis, get_storage
from app.routes.streams.dto import StreamEvent, StreamListResponse


router = APIRouter(prefix="/api/v1/streams", tags=["streams"])


@router.get("", response_model=StreamListResponse)
async def list_streams_route(
    redis: aioredis.Redis = Depends(get_redis),
    config: Config = Depends(get_config),
    storage: PostgresStorage = Depends(get_storage),
) -> StreamListResponse:
    streams = await service.list_streams(redis, config.redis, storage)
    return StreamListResponse(streams=streams)


@router.get("/{stream_id}/events", response_model=list[StreamEvent])
async def get_stream_events_route(
    stream_id: str,
    redis: aioredis.Redis = Depends(get_redis),
    config: Config = Depends(get_config),
) -> list[StreamEvent]:
    return await service.get_stream_events(redis, config.redis, stream_id)


@router.get("/{stream_id}/stream")
async def stream_events_route(
    stream_id: str,
    redis: aioredis.Redis = Depends(get_redis),
    config: Config = Depends(get_config),
) -> StreamingResponse:
    return await service.stream_events(redis, config.redis, stream_id)
