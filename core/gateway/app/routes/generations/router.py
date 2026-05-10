"""Routes under ``/api/v1/generations``.

* ``GET /{generation_id}/metrics`` — token usage + USD cost (LLM-03/04, МТР-03).
* ``GET /{generation_id}/agent-runs`` — paginated Pydantic-AI run history
  (migration 20). Each row carries timing, token usage, success/failure,
  and a primary key the UI uses to fetch the full conversation.
* ``GET /agent-runs/{run_id}`` — the full ``messages`` + ``output`` JSON
  for one row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from source2doc.storage import PostgresStorage

from app.routes.docs.dependencies import get_storage
from app.routes.generations import service
from app.routes.generations.dto import AgentRunDetail, AgentRunsResponse, MetricsResponse


router = APIRouter(prefix="/api/v1/generations", tags=["generations"])


@router.get("/{generation_id}/metrics", response_model=MetricsResponse)
async def get_metrics_route(
    generation_id: str,
    storage: PostgresStorage = Depends(get_storage),
) -> MetricsResponse:
    return await service.get_generation_metrics(storage, generation_id)


@router.get("/{generation_id}/agent-runs", response_model=AgentRunsResponse)
async def list_agent_runs_route(
    generation_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    storage: PostgresStorage = Depends(get_storage),
) -> AgentRunsResponse:
    return await service.list_agent_runs(storage, generation_id, limit=limit, offset=offset)


# Detail endpoint — sibling under the same prefix so the UI only needs
# one base URL. The path doesn't carry ``generation_id`` because the
# numeric ``run_id`` is globally unique (BIGSERIAL primary key).
@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail)
async def get_agent_run_route(
    run_id: int,
    storage: PostgresStorage = Depends(get_storage),
) -> AgentRunDetail:
    return await service.get_agent_run_detail(storage, run_id)
