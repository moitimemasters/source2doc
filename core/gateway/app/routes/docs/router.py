from uuid import UUID

from fastapi import APIRouter, Depends, Query

from source2doc.storage import PostgresStorage

from app.routes.docs import service
from app.routes.docs.dependencies import get_storage
from app.routes.docs.dto import (
    BundleListResponse,
    PageListResponse,
    PageVersionDetailResponse,
    PageVersionListResponse,
)


router = APIRouter(prefix="/api/v1/docs", tags=["documentation"])


@router.get("/bundles", response_model=BundleListResponse)
async def list_bundles_route(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    storage: PostgresStorage = Depends(get_storage),
) -> BundleListResponse:
    bundles = await service.list_bundles(storage, limit, offset)
    return BundleListResponse(bundles=bundles)


@router.get("/bundles/{generation_id}/index")
async def get_bundle_index_route(
    generation_id: UUID,
    storage: PostgresStorage = Depends(get_storage),
) -> dict:
    return await service.get_bundle_index(storage, generation_id)


@router.get("/bundles/{generation_id}/pages", response_model=PageListResponse)
async def list_bundle_pages_route(
    generation_id: UUID,
    storage: PostgresStorage = Depends(get_storage),
) -> PageListResponse:
    pages = await service.list_bundle_pages(storage, generation_id)
    return PageListResponse(pages=pages)


@router.get("/bundles/{generation_id}/pages/{page_id}")
async def get_page_route(
    generation_id: UUID,
    page_id: str,
    storage: PostgresStorage = Depends(get_storage),
) -> dict:
    return await service.get_page(storage, generation_id, page_id)


# B11.2 / ТЗ ГЕН-08 — per-page version history.
#
# Mounted under ``/bundles/{generation_id}/pages/{page_id}/versions`` to
# match the surrounding docs router convention. The wiki UI calls
# ``GET .../versions`` to populate the dropdown and
# ``GET .../versions/{version_generation_id}`` when a reader picks one.
@router.get(
    "/bundles/{generation_id}/pages/{page_id}/versions",
    response_model=PageVersionListResponse,
)
async def list_page_versions_route(
    generation_id: UUID,
    page_id: str,
    storage: PostgresStorage = Depends(get_storage),
) -> PageVersionListResponse:
    versions = await service.list_page_versions(storage, generation_id, page_id)
    return PageVersionListResponse(versions=versions)


@router.get(
    "/bundles/{generation_id}/pages/{page_id}/versions/{version_generation_id}",
    response_model=PageVersionDetailResponse,
)
async def get_page_version_route(
    generation_id: UUID,
    page_id: str,
    version_generation_id: UUID,
    storage: PostgresStorage = Depends(get_storage),
) -> PageVersionDetailResponse:
    return await service.get_page_version(
        storage,
        generation_id,
        page_id,
        version_generation_id,
    )
