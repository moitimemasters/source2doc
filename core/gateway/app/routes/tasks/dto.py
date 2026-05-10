from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr


class LLMConfigRequest(BaseModel):
    provider: str = Field(..., description="openai, openai-compatible, anthropic, yandex, ollama")
    model: str = Field(..., description="Model name")
    api_key: SecretStr = Field(..., description="API key")
    base_url: str | None = Field(None, description="Custom base URL")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, gt=0)
    max_sessions: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Cluster-wide cap on parallel LLM sessions for this API key. "
            "When set, the worker acquires a Redis-backed semaphore "
            "(keyed by sha256 of the api_key) before each agent.run, "
            "throttling all roles (writer/critic/diagrammer/planner/...) "
            "to a shared pool. Set to your provider's inflight limit "
            "(Eliza default: 5) to avoid HTTP 429."
        ),
    )


class EmbeddingsConfigRequest(BaseModel):
    provider: str = Field(default="openai", description="openai, openai-compatible")
    model: str = Field(default="text-embedding-3-small")
    api_key: SecretStr = Field(..., description="API key")
    base_url: str | None = None
    dimensions: int = Field(default=1536, gt=0)
    batch_size: int = Field(default=100, gt=0)
    concurrency: int = Field(default=4, ge=1)


class QdrantConfigRequest(BaseModel):
    url: str = Field(default="http://localhost:6333")
    collection: str = Field(default="docgen")
    api_key: SecretStr | None = None


class PostgresConfigRequest(BaseModel):
    connection_string: SecretStr | None = None


class GenerationConfigRequest(BaseModel):
    min_citations: int = Field(default=3, ge=1)
    max_nodes: int = Field(default=50, ge=1)
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)
    search_limit: int = Field(default=5, ge=1)
    min_page_score: int = Field(default=7, ge=1, le=10)
    max_page_retries: int = Field(default=2, ge=0)
    max_hallucination_retries: int = Field(default=3, ge=1)
    output_language: Literal["en", "ru"] = Field(
        default="en",
        description=(
            "Natural language of the generated documentation. All agents "
            "(planner, subplanner, writer, critic, diagrammer, normalizer) "
            "render their output in this locale; the critic also flags "
            "pages whose body drifts to a different language."
        ),
    )


class TaskRequest(BaseModel):
    repo_id: str = Field(..., description="Repository ID in S3")
    name: str | None = Field(
        None,
        description="Human-readable name for the documentation (defaults to repository name)",
    )
    description: str | None = Field(
        None,
        description="Description of the documentation generation",
    )
    preset: str | None = Field(
        None,
        description="Named server-side preset to use. If omitted the default preset is used. "
        "Any explicit `llm`/`embeddings`/`qdrant` blocks below override the preset field-by-field.",
    )
    llm: LLMConfigRequest | None = Field(
        None,
        description="Optional override of the preset LLM configuration.",
    )
    embeddings: EmbeddingsConfigRequest | None = Field(
        None,
        description="Optional override of the preset embeddings configuration.",
    )
    qdrant: QdrantConfigRequest | None = Field(
        None,
        description="Optional override of the preset Qdrant configuration.",
    )
    postgres: PostgresConfigRequest | None = Field(
        None,
        description="Optional Postgres config (rarely used)",
    )
    generation: GenerationConfigRequest = Field(default_factory=GenerationConfigRequest)
    # B2.4 / ТЗ ИНТ-04 — opt-in full re-embedding. Default False enables
    # incremental indexing (skip files whose sha256 matches the prior run).
    # Set to True to force the embedder to re-process every file even when
    # the hash table says nothing changed. Useful when the embedding model
    # changes or after a manual Qdrant wipe.
    force_reindex: bool = Field(
        default=False,
        description=(
            "If true, ignore the per-repo file-hash table and re-embed every "
            "file. Defaults to false — incremental indexing reuses unchanged "
            "files' embeddings from the previous generation."
        ),
    )


class TaskResponse(BaseModel):
    generation_id: UUID
    name: str | None = None
    trace_id: str | None = None
    status: str
    message: str
    stream_url: str
    events_url: str


class IterativeTaskRequest(BaseModel):
    """Request body for ``POST /api/v1/tasks/incremental``.

    Mirrors :class:`TaskRequest` (same LLM/embeddings/qdrant/preset shape)
    plus the iterative-mode envelope: a base bundle to derive from and
    the set of files that changed (or were deleted) since. The worker:

      * carries forward pages whose ``source_files`` don't intersect
        ``changed_files``;
      * marks pages whose source files were entirely deleted as deprecated
        in the new bundle (``documentation_pages.deprecated = TRUE``);
      * re-runs the writer (in update-mode, with the prior body + diff
        context) for pages whose source files changed;
      * synthesises fresh page specs for changed files not covered by any
        existing page (``orphan files``) and writes them in normal mode.
    """

    repo_id: str = Field(..., description="Repository ID (UUID) the iterative run targets.")
    base_generation_id: str | None = Field(
        default=None,
        description=(
            "Generation ID of the base bundle to derive from. If omitted, "
            "the most recent bundle for ``repo_id`` is used."
        ),
    )
    changed_files: list[str] = Field(
        default_factory=list,
        max_length=1000,
        description=(
            "Repo-relative file paths that changed since the base bundle. "
            "Files not covered by any base-bundle page become orphan-mode "
            "pages; files covered by an existing page trigger a writer "
            "rewrite for that page. Either this OR ``from_commit``+"
            "``to_commit`` must be supplied."
        ),
    )
    deleted_files: list[str] = Field(
        default_factory=list,
        max_length=1000,
        description=(
            "Repo-relative file paths that were removed since the base "
            "bundle. Pages whose ``source_files`` are entirely covered by "
            "this set are copied to the new bundle with ``deprecated=TRUE``."
        ),
    )
    from_commit: str | None = Field(
        default=None,
        description=(
            "Optional base commit SHA. Combined with ``to_commit`` lets the "
            "worker compute ``changed_files`` + ``deleted_files`` itself via "
            "``git diff`` over the cloned repo. Useful for CI flows that "
            "don't want to parse the diff client-side."
        ),
    )
    to_commit: str | None = Field(
        default=None,
        description=(
            "Optional head commit SHA. See ``from_commit``. When both are "
            "supplied and the request omits ``changed_files`` / "
            "``deleted_files``, the worker computes them at runtime."
        ),
    )
    head_sha: str | None = Field(
        default=None,
        description="Optional HEAD commit SHA, displayed on copied/rewritten pages.",
    )
    name: str | None = None
    description: str | None = None
    preset: str | None = None
    llm: LLMConfigRequest | None = None
    embeddings: EmbeddingsConfigRequest | None = None
    qdrant: QdrantConfigRequest | None = None
    postgres: PostgresConfigRequest | None = None
    generation: GenerationConfigRequest = Field(default_factory=GenerationConfigRequest)
    force_reindex: bool = Field(
        default=False,
        description=(
            "If true, the underlying B2.4 embedding cache is bypassed and "
            "every file is re-embedded. Iterative mode itself still skips "
            "the planner — this only affects ingest/index."
        ),
    )


class IterativeTaskResponse(BaseModel):
    """Response for ``POST /api/v1/tasks/incremental``."""

    generation_id: UUID
    base_generation_id: str
    name: str | None = None
    trace_id: str | None = None
    status: str
    message: str
    stream_url: str
    events_url: str


class RetryTaskResponse(BaseModel):
    """Response for ``POST /api/v1/tasks/{id}/retry``.

    Mirrors :class:`TaskResponse` but also carries ``retried_from`` so the
    UI can link back to the original failed run.
    """

    generation_id: UUID
    retried_from: str
    trace_id: str
    status: str
    message: str
    stream_url: str
    events_url: str


class ResumedFromEvent(BaseModel):
    """Reference to the ``*.completed`` event the worker will re-process to
    pick the failed run back up. ``id`` is a Redis stream entry id of the
    *original* successful event (not the freshly re-emitted copy)."""

    type: str
    id: str


class ResumeTaskResponse(BaseModel):
    """Response for ``POST /api/v1/tasks/{id}/resume``.

    Unlike retry, resume keeps the original ``generation_id``, qdrant
    collection, bundle row, and Redis state. The endpoint re-emits the
    last successful transition event into ``events:{gen_id}``; the worker
    consumer picks that up and dispatches the next-phase handler that
    failed last time.
    """

    generation_id: UUID
    resumed_from_event: ResumedFromEvent
    status: str
    message: str
    stream_url: str
    events_url: str
    warnings: list[str] = Field(default_factory=list)


class StepInfo(BaseModel):
    step_name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    error_type: str | None = None
    error_is_transient: bool = False
    attempt_number: int = 1
    max_attempts: int = 3


class RepositoryInfoShort(BaseModel):
    name: str
    source_type: str
    git_url: str | None = None
    git_branch: str | None = None


class TaskStatusResponse(BaseModel):
    generation_id: str
    name: str | None = None
    description: str | None = None
    worker_id: str | None = None
    status: str
    repo_id: str | None = None
    repository: RepositoryInfoShort | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    last_completed_step: str | None = None
    created_at: str
    updated_at: str
    steps: list[StepInfo] = Field(default_factory=list)
