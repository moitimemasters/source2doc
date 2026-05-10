from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from source2doc.storage import S3Storage

from app.config import Config, get_config
from app.routes.bundles import service
from app.routes.bundles.dto import BundleExportRequest, BundleExportResponse
from app.routes.streams.dependencies import get_redis


router = APIRouter(prefix="/api/v1/bundles", tags=["bundles"])


def get_s3_storage(config: Config = Depends(get_config)) -> S3Storage:
    return S3Storage(config.s3)


@router.post("/export", response_model=BundleExportResponse)
async def export_bundle(
    request: BundleExportRequest,
    redis: aioredis.Redis = Depends(get_redis),
    config: Config = Depends(get_config),
) -> BundleExportResponse:
    await service.create_bundle_export_task(
        request.model_dump(),
        config.postgres,
        redis,
    )

    return BundleExportResponse(
        bundle_id=request.bundle_id,
        generation_id=request.generation_id,
        format=request.format,
        message=f"Bundle export task created for format {request.format}",
    )


@router.get("/exports")
async def list_bundle_exports(
    bundle_id: int = Query(..., ge=1),
    s3: S3Storage = Depends(get_s3_storage),
) -> dict:
    exports = await service.list_bundle_exports(s3, bundle_id)
    return {"exports": exports}


@router.get("/exports/download")
async def download_bundle_export(
    s3_key: str = Query(..., min_length=1),
    s3: S3Storage = Depends(get_s3_storage),
) -> StreamingResponse:
    return await service.download_bundle_export(s3, s3_key)
