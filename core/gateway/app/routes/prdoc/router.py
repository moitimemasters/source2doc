"""POST /api/v1/prdoc + GET /api/v1/prdoc/{generation_id}.

Closes ТЗ items ИНТ-02 (Github PR comment auto-generation hook) and
ГЕН-06 (concise diff summarization). The endpoint accepts a small diff
snapshot, hands it off to the prdoc worker via Redis Streams, and
exposes the persisted summary once the worker is done.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
import redis.asyncio as aioredis

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.prdoc import PRDocStorage
from source2doc.storage.presets import ConfigPresetStorage

from app.routes.admin.presets.dependencies import get_preset_storage
from app.routes.prdoc import service
from app.routes.prdoc.dependencies import get_encryption, get_prdoc_storage
from app.routes.prdoc.dto import PRDocRequest, PRDocResponse, PRDocResult
from app.routes.streams.dependencies import get_redis


router = APIRouter(prefix="/api/v1/prdoc", tags=["prdoc"])


@router.post("", response_model=PRDocResponse)
async def create_prdoc_route(
    request: PRDocRequest,
    redis: aioredis.Redis = Depends(get_redis),
    encryption: ConfigEncryption = Depends(get_encryption),
    storage: PRDocStorage = Depends(get_prdoc_storage),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> JSONResponse:
    response = await service.create_prdoc(request, redis, encryption, storage, presets)
    # 202 Accepted matches the contract — the worker is still going to do
    # the actual generation asynchronously.
    return JSONResponse(status_code=202, content=response.model_dump(mode="json"))


@router.get("/{generation_id}", response_model=PRDocResult)
async def get_prdoc_route(
    generation_id: UUID,
    storage: PRDocStorage = Depends(get_prdoc_storage),
) -> PRDocResult:
    return await service.get_prdoc(generation_id, storage)
