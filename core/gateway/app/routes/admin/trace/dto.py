from typing import Any

from pydantic import BaseModel


class TraceEvent(BaseModel):
    id: str
    type: str
    data: dict[str, Any]
    timestamp: str | None = None


class TraceLogEntry(BaseModel):
    id: str
    level: str
    event: str
    timestamp: str | None = None
    logger: str | None = None
    extras: str | None = None


class TraceMetric(BaseModel):
    step: str
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    step_started_at: str | None = None
    step_ended_at: str | None = None


class TraceTotals(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0


class TraceGeneration(BaseModel):
    generation_id: str
    events: list[TraceEvent] = []
    logs: list[TraceLogEntry] = []
    metrics: list[TraceMetric] = []
    totals: TraceTotals = TraceTotals()
    truncated: bool = False


class TraceDiagnosticResponse(BaseModel):
    trace_id: str
    generations: list[TraceGeneration] = []
    checked_at: str
