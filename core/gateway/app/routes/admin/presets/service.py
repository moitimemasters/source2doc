from __future__ import annotations

from fastapi import HTTPException, status

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.presets import ConfigPresetStorage, Preset, PresetMeta

from app.routes.admin.presets import dto


def _serialize_agent_override(override: dto.AgentLLMOverride) -> dict:
    return {
        "provider": override.provider,
        "model": override.model,
        "api_key": override.api_key.get_secret_value(),
        "base_url": override.base_url,
        "temperature": override.temperature,
        "max_tokens": override.max_tokens,
    }


def _serialize_payload(payload: dto.PresetPayload) -> dict:
    data: dict = {
        "llm": {
            "provider": payload.llm.provider,
            "model": payload.llm.model,
            "api_key": payload.llm.api_key.get_secret_value(),
            "base_url": payload.llm.base_url,
            "temperature": payload.llm.temperature,
            "max_tokens": payload.llm.max_tokens,
        },
        "embeddings": {
            "provider": payload.embeddings.provider,
            "model": payload.embeddings.model,
            "api_key": payload.embeddings.api_key.get_secret_value(),
            "base_url": payload.embeddings.base_url,
            "dimensions": payload.embeddings.dimensions,
            "batch_size": payload.embeddings.batch_size,
            "concurrency": payload.embeddings.concurrency,
        },
    }
    if payload.qdrant:
        data["qdrant"] = {
            "url": payload.qdrant.url,
            "api_key": payload.qdrant.api_key.get_secret_value() if payload.qdrant.api_key else None,
        }
    if payload.agents:
        agents: dict = {}
        for role in ("planner", "subplanner", "writer", "diagrammer", "critic", "normalizer"):
            override = getattr(payload.agents, role)
            if override is not None:
                agents[role] = _serialize_agent_override(override)
        if agents:
            data["agents"] = agents
    return data


def _meta_to_response(meta: PresetMeta) -> dto.PresetMetaResponse:
    return dto.PresetMetaResponse(
        id=meta.id,
        name=meta.name,
        is_default=meta.is_default,
        description=meta.description,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
    )


def _preset_to_detail(
    preset: Preset,
    *,
    encryption: ConfigEncryption,
    reveal: bool,
) -> dto.PresetDetailResponse:
    config: dict | None = None
    if reveal:
        config = encryption.decrypt_config(preset.encrypted_config)
    return dto.PresetDetailResponse(
        id=preset.id,
        name=preset.name,
        is_default=preset.is_default,
        description=preset.description,
        created_at=preset.created_at,
        updated_at=preset.updated_at,
        config=config,
    )


async def list_presets(presets: ConfigPresetStorage) -> dto.PresetListResponse:
    items = await presets.list()
    return dto.PresetListResponse(presets=[_meta_to_response(item) for item in items])


async def get_preset(
    preset_id: int,
    *,
    reveal: bool,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> dto.PresetDetailResponse:
    preset = await presets.get(preset_id)
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found")
    return _preset_to_detail(preset, encryption=encryption, reveal=reveal)


async def create_preset(
    request: dto.PresetCreateRequest,
    *,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> dto.PresetDetailResponse:
    encrypted = encryption.encrypt_config(_serialize_payload(request.config))
    try:
        preset_id = await presets.create(
            name=request.name,
            encrypted_config=encrypted,
            description=request.description,
            is_default=request.is_default,
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Preset with name '{request.name}' already exists",
            ) from exc
        raise
    return await get_preset(
        preset_id, reveal=False, presets=presets, encryption=encryption
    )


async def update_preset(
    preset_id: int,
    request: dto.PresetUpdateRequest,
    *,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> dto.PresetDetailResponse:
    encrypted = (
        encryption.encrypt_config(_serialize_payload(request.config))
        if request.config
        else None
    )
    updated = await presets.update(
        preset_id,
        name=request.name,
        description=request.description,
        encrypted_config=encrypted,
        is_default=request.is_default,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found")
    return await get_preset(
        preset_id, reveal=False, presets=presets, encryption=encryption
    )


async def delete_preset(preset_id: int, *, presets: ConfigPresetStorage) -> None:
    deleted = await presets.delete(preset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found")


async def set_default(
    preset_id: int,
    *,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> dto.PresetDetailResponse:
    updated = await presets.set_default(preset_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found")
    return await get_preset(
        preset_id, reveal=False, presets=presets, encryption=encryption
    )
