import datetime as dt
import typing as tp
import uuid

import pydantic


StepKind = tp.Literal["entry", "transition", "leaf", "gotcha"]
TourMode = tp.Literal["overview", "deep-dive", "gotchas"]


class StepHighlight(pydantic.BaseModel):
    """A specific line inside the step's code snippet that the reader should
    pay attention to, plus a short note explaining why it matters."""

    line: int = pydantic.Field(..., ge=1, description="1-based absolute line number in the file.")
    note: str = pydantic.Field(..., min_length=3, max_length=240)


class CommitRef(pydantic.BaseModel):
    """Reference to a git commit that explains the 'why' behind the code in
    this step. The tour author should pick the single most relevant commit;
    extra ones can live in the optional list below."""

    sha: str = pydantic.Field(..., min_length=7, max_length=64)
    short_sha: str | None = None
    author: str | None = None
    date: str | None = None
    message: str | None = None


class AuthorshipInfo(pydantic.BaseModel):
    primary_author: str
    primary_share: float = pydantic.Field(default=0.0, ge=0.0, le=1.0)
    last_modified_at: str | None = None
    last_commit: str | None = None
    contributors: list[str] = pydantic.Field(default_factory=list)


class CodeTourStep(pydantic.BaseModel):
    title: str
    description: str
    file: str
    line: int
    end_line: int | None = None
    code: str | None = None
    pattern: str | None = None

    kind: StepKind = pydantic.Field(
        default="transition",
        description="Role of this step in the flow: entry / transition / leaf / gotcha.",
    )
    key_idea: str | None = pydantic.Field(
        default=None,
        max_length=240,
        description="One sentence answering 'why is this code written like this' — "
        "the non-obvious design point or invariant. NOT a restatement of what the code does.",
    )
    highlights: list[StepHighlight] = pydantic.Field(default_factory=list)
    connects_to: list[int] = pydantic.Field(
        default_factory=list,
        description="0-based indices of OTHER steps this one references "
        "(the next step in the flow, or a related deep-dive). No self-references.",
    )

    commits: list[CommitRef] = pydantic.Field(
        default_factory=list,
        description="Git commits that explain why this code looks the way it does. "
        "Use get_history to fetch them — never invent SHAs.",
    )
    authorship: AuthorshipInfo | None = pydantic.Field(
        default=None,
        description="Author / last-modified summary from get_authorship. Optional.",
    )

    @pydantic.field_validator("authorship", mode="before")
    @classmethod
    def _coerce_empty_authorship(cls, value: tp.Any) -> tp.Any:
        # LLMs habitually emit ``"authorship": {}`` when no git data was
        # collected instead of omitting the key — strict ``AuthorshipInfo``
        # then rejects it because ``primary_author`` is required. Treat an
        # empty mapping (or one without primary_author) as "no authorship"
        # rather than a structurally broken step.
        if isinstance(value, dict) and not value.get("primary_author"):
            return None
        return value


class CodeTour(pydantic.BaseModel):
    tour_id: uuid.UUID
    generation_id: uuid.UUID
    title: str
    description: str
    steps: list[CodeTourStep]
    created_at: dt.datetime
    metadata: dict[str, tp.Any] = pydantic.Field(default_factory=dict)


class CodeTourGenerationRequest(pydantic.BaseModel):
    tour_id: uuid.UUID
    query: str
    generation_id: uuid.UUID
    qdrant_collection: str
    max_steps: int = 10
    context_files: list[dict[str, str]] = pydantic.Field(default_factory=list)
    mode: TourMode = "overview"


class CodeTourFollowupRequest(pydantic.BaseModel):
    """Append more steps to an existing completed tour, anchored to one step."""

    tour_id: uuid.UUID
    step_index: int = pydantic.Field(..., ge=0)
    question: str = pydantic.Field(..., min_length=3)
    qdrant_collection: str
    max_new_steps: int = pydantic.Field(default=3, ge=1, le=8)
