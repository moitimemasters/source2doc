from __future__ import annotations

import typing as tp

from fastapi import HTTPException, status
from pydantic import BaseModel, SecretStr

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage.presets import ConfigPresetStorage


class ResolvedConfigs(tp.TypedDict, total=False):
    llm: dict[str, tp.Any]
    embeddings: dict[str, tp.Any]
    qdrant: dict[str, tp.Any]
    agents: dict[str, tp.Any]


def _model_to_serializable(model: BaseModel | None) -> dict[str, tp.Any] | None:
    if model is None:
        return None
    out: dict[str, tp.Any] = {}
    for key, value in model.model_dump(exclude_none=False).items():
        if isinstance(value, SecretStr):
            out[key] = value.get_secret_value()
        else:
            out[key] = value
    # Pydantic SecretStr fields show up as plain str via model_dump(); but if the
    # model was constructed from raw dict with SecretStr type, model_dump above
    # produces the secret in plaintext when mode="python". Re-walk via raw attrs
    # for any SecretStr that survived.
    for field_name in model.model_fields:
        attr = getattr(model, field_name, None)
        if isinstance(attr, SecretStr):
            out[field_name] = attr.get_secret_value()
    return out


async def resolve_configs(
    *,
    request_llm: BaseModel | None,
    request_embeddings: BaseModel | None,
    request_qdrant: BaseModel | None,
    preset_name: str | None,
    presets: ConfigPresetStorage,
    encryption: ConfigEncryption,
) -> ResolvedConfigs:
    """Merge request fields with the named/default preset.

    Request-supplied fields override the preset field-by-field. Raises 503 when
    neither source provides the required `llm` or `embeddings` blocks.
    """

    base: dict[str, tp.Any] = {}
    if preset_name:
        preset = await presets.get_by_name(preset_name)
        if not preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preset '{preset_name}' not found",
            )
        base = encryption.decrypt_config(preset.encrypted_config)
    else:
        default = await presets.get_default()
        if default:
            base = encryption.decrypt_config(default.encrypted_config)

    llm = _model_to_serializable(request_llm) or base.get("llm")
    embeddings = _model_to_serializable(request_embeddings) or base.get("embeddings")
    qdrant = _model_to_serializable(request_qdrant) or base.get("qdrant")
    agents = base.get("agents")

    if not llm:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No LLM config available. Configure a default preset via "
                "/admin/presets or supply `llm` in the request."
            ),
        )
    if not embeddings:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No embeddings config available. Configure a default preset via "
                "/admin/presets or supply `embeddings` in the request."
            ),
        )

    resolved: ResolvedConfigs = {"llm": llm, "embeddings": embeddings}
    if qdrant:
        resolved["qdrant"] = qdrant
    if agents:
        resolved["agents"] = agents
    return resolved
