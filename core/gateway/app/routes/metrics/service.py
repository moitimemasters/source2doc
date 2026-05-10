"""Service layer for the metrics-aggregate dashboard endpoint."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import HTTPException

from source2doc.logging import get_logger
from source2doc.storage import PostgresStorage

from app.routes.metrics.dto import GroupBy, MetricBucket, MetricsAggregateResponse


logger = get_logger(__name__)


_VALID_GROUP_BY: tuple[str, ...] = ("day", "model", "step")


def _decimal_to_float(value: object) -> float | None:
    """Coerce a Decimal/None cost field into a JSON-friendly float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(value: str | None, *, field_name: str) -> dt.datetime | None:
    """Accept ISO 8601 with or without timezone; reject anything else.

    Naive datetimes are normalised to UTC so the asyncpg driver doesn't
    refuse them when comparing against a TIMESTAMPTZ column.
    """
    if value is None or value == "":
        return None
    try:
        # ``fromisoformat`` accepts both 2026-05-05 and 2026-05-05T12:34:56,
        # plus the trailing 'Z' since 3.11.
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be ISO 8601, got: {value}",
        ) from exc

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed


async def get_metrics_aggregate(
    storage: PostgresStorage,
    *,
    date_from: str | None,
    date_to: str | None,
    group_by: str,
) -> MetricsAggregateResponse:
    """Return aggregate metrics, grouped by day / model / step.

    Empty range -> ``buckets=[]``. The UI is responsible for showing an
    empty-state instead of zeroed charts.
    """
    if group_by not in _VALID_GROUP_BY:
        raise HTTPException(
            status_code=422,
            detail=f"group_by must be one of {list(_VALID_GROUP_BY)}, got: {group_by}",
        )

    parsed_from = _parse_iso_datetime(date_from, field_name="from")
    parsed_to = _parse_iso_datetime(date_to, field_name="to")

    if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
        raise HTTPException(
            status_code=422,
            detail="'from' must be earlier than or equal to 'to'",
        )

    rows = await storage.get_metrics_buckets(
        group_by=group_by,
        date_from=parsed_from,
        date_to=parsed_to,
    )

    buckets = [
        MetricBucket(
            key=row["key"],
            tokens=int(row["tokens"] or 0),
            cost_usd=_decimal_to_float(row["cost_usd"]),
            duration_ms_p50=row["duration_ms_p50"],
            duration_ms_p95=row["duration_ms_p95"],
            runs=int(row["runs"] or 0),
        )
        for row in rows
    ]

    # Cast to GroupBy for the typed response — already validated above.
    return MetricsAggregateResponse(group_by=group_by, buckets=buckets)  # type: ignore[arg-type]


__all__ = ["get_metrics_aggregate", "GroupBy"]
