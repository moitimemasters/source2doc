from fastapi import APIRouter, Depends, Query

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.presets import ConfigPresetStorage

from app.routes.admin.presets import dto, service
from app.routes.admin.presets.dependencies import get_preset_storage
from app.routes.codetours.dependencies import get_encryption
from app.security.admin import require_admin


router = APIRouter(
    prefix="/api/v1/admin/presets",
    tags=["admin:presets"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=dto.PresetListResponse)
async def list_presets_route(
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> dto.PresetListResponse:
    return await service.list_presets(presets)


@router.post("", response_model=dto.PresetDetailResponse, status_code=201)
async def create_preset_route(
    request: dto.PresetCreateRequest,
    presets: ConfigPresetStorage = Depends(get_preset_storage),
    encryption: ConfigEncryption = Depends(get_encryption),
) -> dto.PresetDetailResponse:
    return await service.create_preset(request, presets=presets, encryption=encryption)


@router.get("/{preset_id}", response_model=dto.PresetDetailResponse)
async def get_preset_route(
    preset_id: int,
    reveal: bool = Query(default=False),
    presets: ConfigPresetStorage = Depends(get_preset_storage),
    encryption: ConfigEncryption = Depends(get_encryption),
) -> dto.PresetDetailResponse:
    return await service.get_preset(
        preset_id, reveal=reveal, presets=presets, encryption=encryption
    )


@router.put("/{preset_id}", response_model=dto.PresetDetailResponse)
async def update_preset_route(
    preset_id: int,
    request: dto.PresetUpdateRequest,
    presets: ConfigPresetStorage = Depends(get_preset_storage),
    encryption: ConfigEncryption = Depends(get_encryption),
) -> dto.PresetDetailResponse:
    return await service.update_preset(
        preset_id, request, presets=presets, encryption=encryption
    )


@router.delete("/{preset_id}", status_code=204)
async def delete_preset_route(
    preset_id: int,
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> None:
    await service.delete_preset(preset_id, presets=presets)


@router.post("/{preset_id}/set-default", response_model=dto.PresetDetailResponse)
async def set_default_route(
    preset_id: int,
    presets: ConfigPresetStorage = Depends(get_preset_storage),
    encryption: ConfigEncryption = Depends(get_encryption),
) -> dto.PresetDetailResponse:
    return await service.set_default(
        preset_id, presets=presets, encryption=encryption
    )
