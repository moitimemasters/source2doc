"""DTOs for the cross-generation metrics-aggregate endpoint.

Closes ТЗ items МНТ-06, МТР-01, МТР-02 (B3.4) — feeds the admin metrics
dashboard with bucketed token / cost / latency series.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


GroupBy = Literal["day", "model", "step"]


class MetricBucket(BaseModel):
    """One bucket in the aggregate response (a day, a model, or a step)."""

    key: str = Field(
        description=(
            "Bucket label: an ISO date string for ``group_by=day`` "
            "(e.g. ``2026-05-05``), or the model/step name otherwise."
        )
    )
    tokens: int = Field(description="Sum of total_tokens across rows in the bucket.")
    cost_usd: float | None = Field(
        default=None,
        description=(
            "Sum of cost_usd. Null when every row in the bucket had a null "
            "cost (no pricing entry for the model)."
        ),
    )
    duration_ms_p50: int | None = Field(
        default=None,
        description=(
            "Median wall-clock duration in ms. Null when no row in the "
            "bucket carried a timing value (e.g. legacy rows)."
        ),
    )
    duration_ms_p95: int | None = Field(
        default=None,
        description="95th-percentile wall-clock duration in ms.",
    )
    runs: int = Field(description="Number of generation_metrics rows in the bucket.")


class MetricsAggregateResponse(BaseModel):
    """Response for ``GET /api/v1/metrics/aggregate``."""

    group_by: GroupBy
    buckets: list[MetricBucket]
