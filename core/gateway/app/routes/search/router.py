"""POST /api/v1/projects/{repository_id}/search.

Closes ТЗ items ПСК-01..04, ПСК-06 (Осокин) and СКВ-04 — exposes both
semantic (embeddings + Qdrant vectors) and fulltext (Qdrant ``MatchText``)
search over a repository's indexed chunks.
"""

from fastapi import APIRouter, Depends, Request

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage.presets import ConfigPresetStorage

from app.config import Config, get_config
from app.routes.docs.dependencies import get_storage
from app.routes.search import service
from app.routes.search.dto import SearchRequest, SearchResponse


router = APIRouter(prefix="/api/v1/projects", tags=["search"])


def _get_preset_storage(request: Request) -> ConfigPresetStorage:
    return request.app.state.preset_storage


def _get_encryption(request: Request) -> ConfigEncryption:
    return request.app.state.encryption


@router.post("/{repository_id}/search", response_model=SearchResponse)
async def search_route(
    repository_id: str,
    payload: SearchRequest,
    storage: PostgresStorage = Depends(get_storage),
    presets: ConfigPresetStorage = Depends(_get_preset_storage),
    encryption: ConfigEncryption = Depends(_get_encryption),
    config: Config = Depends(get_config),
) -> SearchResponse:
    return await service.search_project(
        repository_id=repository_id,
        request=payload,
        storage=storage,
        presets=presets,
        encryption=encryption,
        app_config=config,
    )
