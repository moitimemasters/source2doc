import typing as tp

import pydantic as pyd
import pydantic_settings as pyd_settings


class LLMConfig(pyd.BaseModel):
    provider: str = pyd.Field(
        default="openai",
        description="LLM provider: openai, openai-compatible, anthropic, yandex, ollama",
    )
    model: str = pyd.Field(default="gpt-4o", description="Model name")
    api_key: str = pyd.Field(description="API key")
    base_url: str | None = pyd.Field(
        default=None,
        description="Custom base URL (for openai-compatible providers, Yandex, etc.)",
    )
    temperature: float = pyd.Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = pyd.Field(default=4000, gt=0)
    retry_max_attempts: int = pyd.Field(
        default=3,
        ge=1,
        le=10,
        description="Max retry attempts for transient HTTP errors against the LLM provider.",
    )
    retry_max_total_seconds: float = pyd.Field(
        default=120.0,
        gt=0,
        description="Hard ceiling on total wall-clock time spent across LLM retries.",
    )
    max_sessions: int | None = pyd.Field(
        default=None,
        ge=1,
        description=(
            "Cluster-wide cap on parallel LLM sessions for this API key. "
            "When set, every ``agent.run`` acquires a Redis-backed semaphore "
            "keyed by ``sha256(api_key)`` before issuing the call; the "
            "counter is shared across all worker processes and all "
            "in-flight tasks that supply the same key. Eliza-class "
            "providers cap inflight LLM calls at a small N (default 5); "
            "set ``max_sessions`` to that value to avoid HTTP 429 cascades. "
            "Leave unset to fall back to the per-process asyncio "
            "semaphore (``BaseAgentConfig.llm_concurrency``)."
        ),
    )

    @pyd.model_validator(mode="after")
    def _validate_provider(self) -> "LLMConfig":
        # Anthropic has no anonymous mode — fail fast at config-load time
        # rather than letting the user wait for the first agent.run to blow up.
        if self.provider == "anthropic" and not self.api_key:
            raise ValueError(
                "LLMConfig.api_key is required when provider='anthropic' "
                "(Anthropic has no anonymous mode).",
            )
        return self


class EmbeddingsConfig(pyd.BaseModel):
    provider: str = pyd.Field(
        default="openai", description="Embeddings provider: openai, openai-compatible"
    )
    model: str = pyd.Field(default="text-embedding-3-small", description="Model name")
    api_key: str = pyd.Field(description="API key")
    base_url: str | None = pyd.Field(
        default=None,
        description="Custom base URL (for openai-compatible providers)",
    )
    dimensions: int = pyd.Field(default=1536, gt=0, description="Embedding dimensions")
    batch_size: int = pyd.Field(default=100, gt=0, description="Batch size for embeddings")
    concurrency: int = pyd.Field(
        default=4, ge=1, description="Number of concurrent embedding requests"
    )


class ResilienceConfig(pyd.BaseModel):
    """Retry budget for transient external-service failures.

    Used by :mod:`source2doc.resilience.external`. Retries only fire on
    network/5xx errors; 4xx (auth, missing-bucket, validation) are not
    retried. Defaults: 3 attempts, with a per-call wall-clock cap.
    """

    max_attempts: int = pyd.Field(
        default=3,
        ge=1,
        description="Maximum number of attempts (initial call + retries).",
    )
    max_total_seconds: float = pyd.Field(
        default=60.0,
        gt=0,
        description="Wall-clock budget across all attempts, in seconds.",
    )


class QdrantConfig(pyd.BaseModel):
    url: str = pyd.Field(default="http://localhost:6333", description="Qdrant server URL")
    collection: str = pyd.Field(default="docgen", description="Collection name")
    api_key: str | None = pyd.Field(default=None, description="API key (optional)")
    resilience: ResilienceConfig = pyd.Field(
        default_factory=lambda: ResilienceConfig(max_attempts=3, max_total_seconds=30.0),
        description="Retry budget for transient Qdrant failures.",
    )


class RedisConfig(pyd.BaseModel):
    url: str = pyd.Field(default="redis://localhost:6379", description="Redis server URL")
    stream_prefix: str = pyd.Field(
        default="events", description="Stream name prefix for event streams"
    )
    consumer_group: str = pyd.Field(default="workers", description="Consumer group name")
    consumer_name: str = pyd.Field(default="worker-1", description="Consumer name")
    block_timeout_ms: int = pyd.Field(
        default=5000, gt=0, description="Block timeout for XREADGROUP in milliseconds"
    )
    max_idle_time_ms: int = pyd.Field(
        default=120000,
        gt=0,
        description="Max idle time for PEL recovery in milliseconds",
    )
    stream_ttl_seconds: int = pyd.Field(
        default=86400,
        gt=0,
        description="Stream TTL for auto-cleanup in seconds (24h default)",
    )
    max_retries: int = pyd.Field(
        default=3,
        ge=1,
        description="Max delivery attempts before message is moved to DLQ",
    )


class PostgresConfig(pyd.BaseModel):
    host: str = pyd.Field(default="localhost", description="PostgreSQL host")
    port: int = pyd.Field(default=5432, description="PostgreSQL port")
    database: str = pyd.Field(default="docgen", description="Database name")
    user: str = pyd.Field(default="docgen", description="Database user")
    password: str = pyd.Field(default="docgen_password", description="Database password")
    pool_min_size: int = pyd.Field(
        default=2,
        ge=1,
        description="asyncpg pool minimum connections.",
    )
    pool_max_size: int = pyd.Field(
        default=10,
        ge=1,
        description=(
            "asyncpg pool maximum connections. Bump on the gateway under load — "
            "the default is fine for workers but can saturate when many SSE "
            "clients are subscribed."
        ),
    )

    @property
    def connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class S3Config(pyd.BaseModel):
    endpoint_url: str = pyd.Field(
        default="http://localhost:4566",
        description="S3 endpoint URL (LocalStack)",
    )
    region: str = pyd.Field(default="us-east-1", description="AWS region")
    access_key_id: str = pyd.Field(default="test", description="AWS access key ID")
    secret_access_key: str = pyd.Field(default="test", description="AWS secret access key")
    bucket: str = pyd.Field(default="source2doc-repos", description="S3 bucket name")
    resilience: ResilienceConfig = pyd.Field(
        default_factory=lambda: ResilienceConfig(max_attempts=3, max_total_seconds=60.0),
        description="Retry budget for transient S3 failures.",
    )


class WorkerConfig(pyd.BaseModel):
    poll_interval_ms: int = pyd.Field(
        default=1000,
        gt=0,
        description="Polling interval in milliseconds",
    )
    retry_delay_ms: int = pyd.Field(
        default=5000,
        gt=0,
        description="Delay between retries in milliseconds",
    )


class LoggingConfig(pyd.BaseModel):
    level: str = pyd.Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")


class LogfireConfig(pyd.BaseModel):
    enabled: bool = pyd.Field(default=False, description="Enable Logfire instrumentation")
    token: str | None = pyd.Field(
        default=None, description="Logfire API token (can use ${LOGFIRE_TOKEN})"
    )


class PromptsConfig(pyd.BaseModel):
    planner: str = pyd.Field(default="prompts/planner.yaml", description="Planner prompt file")
    subplanner: str = pyd.Field(
        default="prompts/subplanner.yaml",
        description="Subplanner prompt file (per-section page-spec generator)",
    )
    writer: str = pyd.Field(default="prompts/writer.yaml", description="Writer prompt file")
    critic: str = pyd.Field(default="prompts/critic.yaml", description="Critic prompt file")
    diagrammer: str = pyd.Field(
        default="prompts/diagrammer.yaml",
        description="Diagrammer prompt file (mermaid placeholder fill agent)",
    )
    normalizer: str = pyd.Field(
        default="prompts/normalizer.yaml",
        description="Normalizer prompt file (post-write block restructure agent)",
    )


class GenerationConfig(pyd.BaseModel):
    min_citations: int = pyd.Field(
        default=3,
        ge=1,
        description="Minimum citations per node",
    )
    max_nodes: int = pyd.Field(default=50, ge=1, description="Maximum documentation nodes")
    chunk_size: int = pyd.Field(
        default=1000,
        gt=0,
        description="Code chunk size in characters",
    )
    chunk_overlap: int = pyd.Field(default=200, ge=0, description="Overlap between chunks")
    search_limit: int = pyd.Field(
        default=5,
        ge=1,
        description="Maximum search results for RAG",
    )
    overlap_lines_divisor: int = pyd.Field(
        default=50,
        gt=0,
        description="Divisor for calculating overlap lines",
    )
    min_page_score: int = pyd.Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum acceptable page quality score",
    )
    max_page_retries: int = pyd.Field(
        default=2,
        ge=0,
        description="Maximum page rewrite attempts",
    )
    max_hallucination_retries: int = pyd.Field(
        default=3,
        ge=1,
        description="Maximum retries for pages with hallucinations",
    )
    max_total_attempts: int = pyd.Field(
        default=6,
        ge=1,
        description=(
            "Hard ceiling on total review attempts per page across all "
            "rejection reasons. Defense-in-depth against a critic that keeps "
            "returning revision_requested past per-reason caps."
        ),
    )
    # Natural-language locale of the rendered documentation (titles,
    # descriptions, paragraphs, callouts, code-comment translations).
    # Independent of ``dominant_language`` (which is the *source code*
    # language of the repo). All agent prompts inject this so writer
    # body / planner section titles / critic feedback / diagrammer labels
    # all match. Two values are wired today: "en" (default) and "ru".
    output_language: tp.Literal["en", "ru"] = pyd.Field(
        default="en",
        description=(
            "Natural language for the generated documentation. 'en' or 'ru'. "
            "All agents render in this language; the critic also flags pages "
            "whose body drifts to a different language."
        ),
    )


AgentRole = tp.Literal[
    "planner",
    "subplanner",
    "writer",
    "diagrammer",
    "critic",
    "normalizer",
]


class AgentLLMOverrides(pyd.BaseModel):
    """Per-agent LLM overrides.

    Each field is optional. When unset, ``AppConfig.resolve_llm(role)`` falls
    back to the top-level ``llm`` so existing configs keep working unchanged.
    """

    planner: LLMConfig | None = None
    subplanner: LLMConfig | None = None
    writer: LLMConfig | None = None
    diagrammer: LLMConfig | None = None
    critic: LLMConfig | None = None
    normalizer: LLMConfig | None = None


class NormalizerConfig(pyd.BaseModel):
    """Block-normalizer phase config.

    The deterministic pre-pass always runs. The LLM second-pass runs when the
    deterministic pre-pass touches more than ``llm_threshold_edits`` blocks,
    or whenever ``always_llm`` is true.
    """

    enabled: bool = pyd.Field(default=True, description="Run the normalize phase at all.")
    always_llm: bool = pyd.Field(
        default=False,
        description="Always run the LLM second-pass, even when the deterministic pass is clean.",
    )
    llm_threshold_edits: int = pyd.Field(
        default=5,
        ge=0,
        description="If deterministic pass made >= this many edits, also run the LLM second-pass.",
    )


class AppConfig(pyd_settings.BaseSettings):
    model_config = pyd_settings.SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    llm: LLMConfig
    agents: AgentLLMOverrides = pyd.Field(default_factory=AgentLLMOverrides)
    embeddings: EmbeddingsConfig
    qdrant: QdrantConfig
    postgres: PostgresConfig = pyd.Field(default_factory=PostgresConfig)
    redis: RedisConfig = pyd.Field(default_factory=RedisConfig)
    worker: WorkerConfig = pyd.Field(default_factory=WorkerConfig)
    logging: LoggingConfig = pyd.Field(default_factory=LoggingConfig)
    logfire: LogfireConfig = pyd.Field(default_factory=LogfireConfig)
    prompts: PromptsConfig = pyd.Field(default_factory=PromptsConfig)
    generation: GenerationConfig = pyd.Field(default_factory=GenerationConfig)
    normalizer: NormalizerConfig = pyd.Field(default_factory=NormalizerConfig)

    def resolve_llm(self, role: AgentRole) -> LLMConfig:
        """Return the override for ``role`` if set, else the top-level ``llm``."""
        override = getattr(self.agents, role, None)
        return override if override is not None else self.llm
