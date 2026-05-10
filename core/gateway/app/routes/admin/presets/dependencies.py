from fastapi import Request

from source2doc.storage.presets import ConfigPresetStorage


async def get_preset_storage(request: Request) -> ConfigPresetStorage:
    return request.app.state.preset_storage
