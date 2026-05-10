from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from app.routes.logs import service
from app.routes.logs.dto import LogsResponse


router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


async def _get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


@router.get("/{generation_id}", response_model=LogsResponse)
async def get_logs_route(
    generation_id: str,
    redis: aioredis.Redis = Depends(_get_redis),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> LogsResponse:
    return await service.get_logs(redis, generation_id, from_iso=from_, to_iso=to)


@router.get("/{generation_id}/stream")
async def stream_logs_route(
    generation_id: str,
    redis: aioredis.Redis = Depends(_get_redis),
) -> StreamingResponse:
    return await service.stream_logs(redis, generation_id)
