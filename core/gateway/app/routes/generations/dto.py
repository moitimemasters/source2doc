"""DTOs for the per-generation metrics + agent-runs endpoints.

Closes ТЗ items LLM-03, LLM-04, МТР-03 — exposes aggregated token usage
and USD cost stored in ``generation_metrics``. The agent-runs DTOs added
on top expose the full Pydantic-AI message history (migration 20) so the
UI can replay a generation conversation by conversation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MetricStep(BaseModel):
    """One row of the per-step breakdown."""

    step: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None = None
    created_at: str


class MetricTotals(BaseModel):
    """Aggregate token usage + cost across every step."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = Field(
        default=None,
        description=(
            "Sum of cost_usd across all rows. Null when no row had a "
            "priced model (the pricing map didn't cover any model used)."
        ),
    )


class MetricsResponse(BaseModel):
    generation_id: str
    totals: MetricTotals
    steps: list[MetricStep]


class AgentRunSummary(BaseModel):
    """One row of the agent-runs table view (no message body).

    Returned by ``GET /api/v1/generations/{id}/agent-runs`` so the UI can
    render a sortable grid without paying the cost of streaming full
    ``messages`` JSONB blobs for every entry. The detail panel issues a
    second request against ``/agent-runs/{run_id}`` to fetch the full
    conversation when the user clicks a row.
    """

    id: int
    generation_id: str
    page_id: str | None = None
    section_id: str | None = None
    agent_name: str
    attempt: int
    started_at: str
    finished_at: str | None = None
    duration_ms: int | None = None
    success: bool
    error_type: str | None = None
    error_message: str | None = None
    request_count: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    trace_id: str | None = None


class AgentRunsResponse(BaseModel):
    """Paginated listing of ``agent_runs`` rows for one generation."""

    generation_id: str
    items: list[AgentRunSummary]
    limit: int
    offset: int


class AgentRunDetail(AgentRunSummary):
    """Full ``agent_runs`` row including ``messages`` and ``output`` JSON.

    The ``messages`` field carries the same shape Pydantic-AI emits via
    ``ModelMessagesTypeAdapter.dump_python(mode='json')`` — a list of
    ``{kind, parts: [...]}`` entries — but it's typed as ``Any`` here
    because the SDK shape is unstable across versions and the UI doesn't
    introspect specific fields beyond the top-level role tag.
    """

    messages: Any
    output: Any = None
