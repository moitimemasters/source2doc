from fastapi import APIRouter, HTTPException

from source2doc.pipelines import PIPELINES, Pipeline


router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])


@router.get("")
async def list_pipelines_route() -> list[dict]:
    return [{"id": p.id, "label": p.label} for p in PIPELINES.values()]


@router.get("/{pipeline_id}/schema", response_model=Pipeline)
async def get_pipeline_schema_route(pipeline_id: str) -> Pipeline:
    pipeline = PIPELINES.get(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"unknown pipeline {pipeline_id!r}")
    return pipeline
