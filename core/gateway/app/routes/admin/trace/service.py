"""Diagnostic gather for a single trace_id (B13.4 / СПР-04).

We pull everything we know about an operation across three substrates:

* PostgreSQL `generation_metrics` (per-step token / cost rows tagged with
  `trace_id`) — primary discovery source for which generations were
  involved.
* Redis events stream `{stream_prefix}:{generation_id}` — pipeline
  status events. Filtered to entries whose serialized `data.trace_id`
  matches the requested trace.
* Redis logs stream `logs:{generation_id}` — structured log lines from
  workers; we honour the same trace filter.

The reads are bounded (`MAX_STREAM_ENTRIES`) so a misuse can never put
the gateway into an unbounded scan path.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis

from source2doc.config import RedisConfig
from source2doc.storage import GenerationMetric, PostgresStorage

from app.routes.admin.trace.dto import (
    TraceDiagnosticResponse,
    TraceEvent,
    TraceGeneration,
    TraceLogEntry,
    TraceMetric,
    TraceTotals,
)


LOG_STREAM_PREFIX = "logs"
MAX_STREAM_ENTRIES = 1000


def _event_time_iso(message_id: str | None) -> str | None:
    if not message_id:
        return None
    try:
        ms = int(str(message_id).split("-", 1)[0])
    except (ValueError, AttributeError):
        return None
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.UTC).isoformat()


def _entry_matches_trace(payload: dict[str, Any], trace_id: str) -> bool:
    """Match an event/log payload against the requested trace_id.

    We accept either a top-level `trace_id` field or a nested one inside
    `extras` (the Redis-stream structlog handler stringifies extras into
    the `extras` field on log entries — so we also try parsing that
    string).
    """
    candidate = payload.get("trace_id")
    if isinstance(candidate, str) and candidate == trace_id:
        return True
    extras = payload.get("extras")
    if isinstance(extras, dict) and extras.get("trace_id") == trace_id:
        return True
    if isinstance(extras, str):
        try:
            parsed = json.loads(extras)
        except (TypeError, ValueError):
            return False
        if isinstance(parsed, dict) and parsed.get("trace_id") == trace_id:
            return True
    return False


async def _fetch_events_for_trace(
    redis: aioredis.Redis,
    config: RedisConfig,
    generation_id: UUID,
    trace_id: str,
) -> tuple[list[TraceEvent], bool]:
    stream_key = f"{config.stream_prefix}:{generation_id}"
    try:
        entries = await redis.xrevrange(stream_key, count=MAX_STREAM_ENTRIES)
    except Exception:
        return [], False

    truncated = len(entries) >= MAX_STREAM_ENTRIES
    # xrevrange returns newest-first; flip so callers see chronological order.
    entries = list(reversed(entries))
    events: list[TraceEvent] = []
    for message_id, fields in entries:
        try:
            data = json.loads(fields.get("data", "{}"))
        except (TypeError, ValueError):
            data = {}
        if not _entry_matches_trace(data, trace_id):
            continue
        events.append(
            TraceEvent(
                id=message_id,
                type=fields.get("type", "unknown"),
                data=data,
                timestamp=_event_time_iso(message_id),
            )
        )
    return events, truncated


async def _fetch_logs_for_trace(
    redis: aioredis.Redis,
    generation_id: UUID,
    trace_id: str,
) -> tuple[list[TraceLogEntry], bool]:
    stream_key = f"{LOG_STREAM_PREFIX}:{generation_id}"
    try:
        entries = await redis.xrevrange(stream_key, count=MAX_STREAM_ENTRIES)
    except Exception:
        return [], False

    truncated = len(entries) >= MAX_STREAM_ENTRIES
    entries = list(reversed(entries))
    logs: list[TraceLogEntry] = []
    for message_id, fields in entries:
        if not _entry_matches_trace(dict(fields), trace_id):
            continue
        logs.append(
            TraceLogEntry(
                id=message_id,
                level=fields.get("level", "info"),
                event=fields.get("event", ""),
                timestamp=fields.get("timestamp") or _event_time_iso(message_id),
                logger=fields.get("logger"),
                extras=fields.get("extras"),
            )
        )
    return logs, truncated


def _cost_to_float(value: Any) -> float:
    """Convert ``GenerationMetric.cost_usd`` (``Decimal | float | None``) to float.

    Main's storage layer returns ``Decimal | None`` while B13.4's totals math
    needs a plain float. ``None`` is treated as ``0.0`` so a row without a
    priced model contributes nothing.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _metric_to_dto(metric: GenerationMetric) -> TraceMetric:
    return TraceMetric(
        step=metric.step,
        model=metric.model,
        prompt_tokens=metric.prompt_tokens,
        completion_tokens=metric.completion_tokens,
        cost_usd=_cost_to_float(metric.cost_usd),
        duration_ms=metric.duration_ms or 0,
        step_started_at=metric.step_started_at,
        step_ended_at=metric.step_completed_at,
    )


def _totals(metrics: list[GenerationMetric]) -> TraceTotals:
    total_prompt = sum(m.prompt_tokens for m in metrics)
    total_completion = sum(m.completion_tokens for m in metrics)
    total_cost = sum(_cost_to_float(m.cost_usd) for m in metrics)
    total_ms = sum(m.duration_ms or 0 for m in metrics)
    return TraceTotals(
        prompt_tokens=total_prompt,
        completion_tokens=total_completion,
        cost_usd=round(total_cost, 6),
        duration_s=round(total_ms / 1000.0, 3),
    )


async def collect_trace_diagnostic(
    trace_id: str,
    *,
    redis: aioredis.Redis,
    redis_config: RedisConfig,
    storage: PostgresStorage,
) -> TraceDiagnosticResponse:
    """Build the diagnostic blob for `trace_id`. Empty if nothing matches."""

    generation_ids = await storage.find_generations_by_trace_id(trace_id)
    metrics_by_trace = await storage.get_metrics_by_trace_id(trace_id)

    metrics_by_gen: dict[UUID, list[GenerationMetric]] = {}
    for metric in metrics_by_trace:
        metrics_by_gen.setdefault(metric.generation_id, []).append(metric)

    # Union: any generation we discovered through metrics or through the
    # explicit lookup above. Preserve order of discovery.
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    for gen_id in (*generation_ids, *metrics_by_gen.keys()):
        if gen_id in seen:
            continue
        seen.add(gen_id)
        ordered.append(gen_id)

    generations: list[TraceGeneration] = []
    for gen_id in ordered:
        events, events_truncated = await _fetch_events_for_trace(
            redis, redis_config, gen_id, trace_id
        )
        logs, logs_truncated = await _fetch_logs_for_trace(redis, gen_id, trace_id)
        gen_metrics = metrics_by_gen.get(gen_id, [])

        generations.append(
            TraceGeneration(
                generation_id=str(gen_id),
                events=events,
                logs=logs,
                metrics=[_metric_to_dto(m) for m in gen_metrics],
                totals=_totals(gen_metrics),
                truncated=events_truncated or logs_truncated,
            )
        )

    return TraceDiagnosticResponse(
        trace_id=trace_id,
        generations=generations,
        checked_at=dt.datetime.now(dt.UTC).isoformat(),
    )
