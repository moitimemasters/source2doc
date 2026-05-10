from fastapi import APIRouter, Depends
import redis.asyncio as aioredis

from source2doc.storage import PostgresStorage

from app.config import Config, get_config
from app.routes.admin.trace import service
from app.routes.admin.trace.dto import TraceDiagnosticResponse
from app.routes.streams.dependencies import get_redis, get_storage
from app.security.admin import require_admin


router = APIRouter(
    prefix="/api/v1/admin/trace",
    tags=["admin:trace"],
    dependencies=[Depends(require_admin)],
)


@router.get("/{trace_id}", response_model=TraceDiagnosticResponse)
async def get_trace_diagnostic_route(
    trace_id: str,
    redis: aioredis.Redis = Depends(get_redis),
    config: Config = Depends(get_config),
    storage: PostgresStorage = Depends(get_storage),
) -> TraceDiagnosticResponse:
    """Gather everything we know about `trace_id` (events, logs, metrics)."""
    return await service.collect_trace_diagnostic(
        trace_id,
        redis=redis,
        redis_config=config.redis,
        storage=storage,
    )
