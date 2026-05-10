import typing as tp
from uuid import UUID

from pydantic import BaseModel, Field

from source2doc.config import EmbeddingsConfig, LLMConfig, QdrantConfig


TourMode = tp.Literal["overview", "deep-dive", "gotchas"]


class CodetourRequest(BaseModel):
    """Public end-user code-tour request — no LLM credentials accepted in body.

    The gateway resolves LLM/embeddings/qdrant from the configured default preset.
    """

    generation_id: UUID = Field(
        ...,
        description="Generation ID from documentation bundle for RAG context.",
    )
    query: str = Field(
        ...,
        min_length=1,
        description="User query for the code tour (e.g., 'How to add middleware').",
    )
    max_steps: int = Field(default=10, ge=1, le=30)
    mode: TourMode = Field(default="overview")
    repo_id: UUID | None = Field(default=None)


class AdminCodetourRequest(CodetourRequest):
    """Admin variant — may override the preset LLM/embeddings/qdrant."""

    preset: str | None = Field(default=None, description="Named preset (default if omitted).")
    llm: LLMConfig | None = Field(default=None)
    embeddings: EmbeddingsConfig | None = Field(default=None)
    qdrant: QdrantConfig | None = Field(default=None)


class CodetourFollowupRequest(BaseModel):
    """Public follow-up — no LLM credentials accepted in body."""

    step_index: int = Field(..., ge=0)
    question: str = Field(..., min_length=3)
    max_new_steps: int = Field(default=3, ge=1, le=8)


class AdminCodetourFollowupRequest(CodetourFollowupRequest):
    preset: str | None = Field(default=None)
    llm: LLMConfig | None = None
    embeddings: EmbeddingsConfig | None = None
    qdrant: QdrantConfig | None = None


class CodetourFollowupResponse(BaseModel):
    tour_id: UUID
    request_id: UUID
    trace_id: str | None = None
    status: str
    message: str


class CodetourResponse(BaseModel):
    tour_id: UUID
    generation_id: UUID
    trace_id: str | None = None
    status: str
    message: str


class CodetourInfo(BaseModel):
    tour_id: str
    generation_id: str
    title: str
    description: str
    created_at: str
    status: str | None = None


class CodetourListResponse(BaseModel):
    tours: list[CodetourInfo]


class StepHighlight(BaseModel):
    line: int
    note: str


class CommitRef(BaseModel):
    sha: str
    short_sha: str | None = None
    author: str | None = None
    date: str | None = None
    message: str | None = None


class AuthorshipInfo(BaseModel):
    primary_author: str
    primary_share: float = 0.0
    last_modified_at: str | None = None
    last_commit: str | None = None
    contributors: list[str] = Field(default_factory=list)


StepKind = tp.Literal["entry", "transition", "leaf", "gotcha"]


class CodetourStep(BaseModel):
    title: str
    description: str
    file: str
    line: int
    end_line: int | None = None
    code: str | None = None
    pattern: str | None = None

    kind: StepKind = "transition"
    key_idea: str | None = None
    highlights: list[StepHighlight] = Field(default_factory=list)
    connects_to: list[int] = Field(default_factory=list)
    commits: list[CommitRef] = Field(default_factory=list)
    authorship: AuthorshipInfo | None = None


class CodetourDetail(BaseModel):
    tour_id: str
    generation_id: str
    title: str
    description: str
    steps: list[CodetourStep]
    created_at: str
    metadata: dict
    status: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
