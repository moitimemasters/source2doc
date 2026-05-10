from pydantic import BaseModel


class RepositoryInfoShort(BaseModel):
    name: str
    source_type: str
    git_url: str | None = None
    git_branch: str | None = None


class StreamInfo(BaseModel):
    stream_id: str
    pipeline_id: str = "docgen"
    event_count: int
    last_event_id: str | None = None
    # Enriched from generation_tasks
    name: str | None = None
    description: str | None = None
    status: str | None = None
    repo_id: str | None = None
    repository: RepositoryInfoShort | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class StreamEvent(BaseModel):
    """One Redis-stream event as delivered over SSE.

    The ``data`` payload is intentionally untyped — every event kind has
    its own shape and the gateway is a pass-through. Notable structured
    fields the UI looks for:

    * ``data.reason`` (free-form string): for ``step.failed`` and
      ``generation.failed`` / ``codetour.failed`` events. Known values:
      - ``"llm_timeout"`` — LLM HTTP call exhausted its retry budget.
        Accompanied by ``error_message``, ``model``, ``elapsed_s``,
        ``last_attempt_n``.
      - ``"max_total_attempts_reached"``, ``"hallucinations_detected"``,
        ``"low_score"`` etc. — pipeline-internal review verdicts.
    """

    id: str
    type: str
    data: dict
    phase: str | None = None
    kind: str | None = None
    trace_id: str | None = None


class StreamListResponse(BaseModel):
    streams: list[StreamInfo]
