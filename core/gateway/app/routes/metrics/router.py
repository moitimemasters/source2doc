"""GET /api/v1/metrics/aggregate.

Closes ТЗ items МНТ-06, МТР-01, МТР-02 (B3.4) — exposes bucketed metrics
for the admin dashboard. The per-generation totals route from B3.1 lives
in ``app.routes.generations`` and is unaffected.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from source2doc.storage import PostgresStorage

from app.routes.docs.dependencies import get_storage
from app.routes.metrics import service
from app.routes.metrics.dto import MetricsAggregateResponse


router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/aggregate", response_model=MetricsAggregateResponse)
async def get_metrics_aggregate_route(
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    group_by: str = Query(default="day"),
    storage: PostgresStorage = Depends(get_storage),
) -> MetricsAggregateResponse:
    return await service.get_metrics_aggregate(
        storage,
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
    )
