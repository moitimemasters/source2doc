"""Service layer for the per-generation metrics + agent-runs endpoints."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException

from source2doc.logging import get_logger
from source2doc.storage import PostgresStorage
from source2doc.storage.postgres import AgentRunRecord

from app.routes.generations.dto import (
    AgentRunDetail,
    AgentRunsResponse,
    AgentRunSummary,
    MetricsResponse,
    MetricStep,
    MetricTotals,
)


logger = get_logger(__name__)


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


def _parse_generation_id(generation_id: str) -> UUID:
    try:
        return UUID(generation_id)
    except ValueError as exc:
        # Use the numeric 422 directly — different starlette versions ship
        # the constant under different names (HTTP_422_UNPROCESSABLE_ENTITY
        # vs _CONTENT). The literal is the stable contract here.
        raise HTTPException(
            status_code=422,
            detail=f"generation_id must be a UUID, got: {generation_id}",
        ) from exc


async def get_generation_metrics(
    storage: PostgresStorage,
    generation_id: str,
) -> MetricsResponse:
    """Return the aggregate + per-step breakdown for a generation.

    A generation with no rows still returns a 200 with zeroed totals — the
    UI treats "no metrics" the same as "no priced data" and just hides the
    badge.
    """
    gen_uuid = _parse_generation_id(generation_id)

    rows = await storage.get_metrics_for_generation(gen_uuid)
    aggregate = await storage.get_metrics_aggregate(gen_uuid)

    steps = [
        MetricStep(
            step=row.step,
            model=row.model,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            total_tokens=row.total_tokens,
            cost_usd=_decimal_to_float(row.cost_usd),
            created_at=row.created_at,
        )
        for row in rows
    ]

    totals = MetricTotals(
        prompt_tokens=int(aggregate.get("prompt_tokens") or 0),
        completion_tokens=int(aggregate.get("completion_tokens") or 0),
        total_tokens=int(aggregate.get("total_tokens") or 0),
        cost_usd=_decimal_to_float(aggregate.get("cost_usd")),
    )

    return MetricsResponse(
        generation_id=generation_id,
        totals=totals,
        steps=steps,
    )


def _summary_from_record(record: AgentRunRecord) -> AgentRunSummary:
    return AgentRunSummary(
        id=record.id,
        generation_id=str(record.generation_id),
        page_id=record.page_id,
        section_id=record.section_id,
        agent_name=record.agent_name,
        attempt=record.attempt,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_ms=record.duration_ms,
        success=record.success,
        error_type=record.error_type,
        error_message=record.error_message,
        request_count=record.request_count,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        total_tokens=record.total_tokens,
        cost_usd=_decimal_to_float(record.cost_usd),
        trace_id=record.trace_id,
    )


async def list_agent_runs(
    storage: PostgresStorage,
    generation_id: str,
    limit: int,
    offset: int,
) -> AgentRunsResponse:
    """Return ``agent_runs`` rows for a generation, newest first."""
    gen_uuid = _parse_generation_id(generation_id)
    rows = await storage.list_agent_runs(gen_uuid, limit=limit, offset=offset)
    return AgentRunsResponse(
        generation_id=generation_id,
        items=[_summary_from_record(row) for row in rows],
        limit=limit,
        offset=offset,
    )


async def get_agent_run_detail(
    storage: PostgresStorage,
    run_id: int,
) -> AgentRunDetail:
    """Fetch one ``agent_runs`` row by primary key (full messages + output)."""
    record = await storage.get_agent_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"agent_run not found: {run_id}")

    summary = _summary_from_record(record)
    return AgentRunDetail(
        **summary.model_dump(),
        messages=record.messages,
        output=record.output,
    )
