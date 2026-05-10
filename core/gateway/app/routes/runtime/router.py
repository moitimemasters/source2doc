from fastapi import APIRouter, Depends
from pydantic import BaseModel

from source2doc.storage.presets import ConfigPresetStorage

from app.routes.admin.presets.dependencies import get_preset_storage


router = APIRouter(prefix="/api/v1/runtime", tags=["runtime"])


class DefaultPresetInfo(BaseModel):
    name: str
    description: str | None = None


class RuntimeInfoResponse(BaseModel):
    default_preset: DefaultPresetInfo | None = None
    presets_count: int = 0
    configured: bool = False


@router.get("/info", response_model=RuntimeInfoResponse)
async def runtime_info(
    presets: ConfigPresetStorage = Depends(get_preset_storage),
) -> RuntimeInfoResponse:
    items = await presets.list()
    default = next((item for item in items if item.is_default), None)
    return RuntimeInfoResponse(
        default_preset=DefaultPresetInfo(name=default.name, description=default.description)
        if default
        else None,
        presets_count=len(items),
        configured=default is not None,
    )
