from pydantic import BaseModel, Field, SecretStr


class LLMPresetConfig(BaseModel):
    provider: str = Field(..., description="openai, openai-compatible, anthropic, yandex, ollama")
    model: str
    api_key: SecretStr
    base_url: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, gt=0)


class EmbeddingsPresetConfig(BaseModel):
    provider: str = Field(default="openai")
    model: str = Field(default="text-embedding-3-small")
    api_key: SecretStr
    base_url: str | None = None
    dimensions: int = Field(default=1536, gt=0)
    batch_size: int = Field(default=100, gt=0)
    concurrency: int = Field(default=4, ge=1)


class QdrantPresetConfig(BaseModel):
    url: str = Field(default="http://localhost:6333")
    api_key: SecretStr | None = None


class AgentLLMOverride(BaseModel):
    """Per-agent LLM override. Only api_key is mandatory because the
    other fields default sensibly via the top-level ``llm`` if missing."""

    provider: str
    model: str
    api_key: SecretStr
    base_url: str | None = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4000, gt=0)


class AgentOverridesPreset(BaseModel):
    planner: AgentLLMOverride | None = None
    subplanner: AgentLLMOverride | None = None
    writer: AgentLLMOverride | None = None
    diagrammer: AgentLLMOverride | None = None
    critic: AgentLLMOverride | None = None
    normalizer: AgentLLMOverride | None = None


class PresetPayload(BaseModel):
    llm: LLMPresetConfig
    embeddings: EmbeddingsPresetConfig
    qdrant: QdrantPresetConfig | None = None
    agents: AgentOverridesPreset | None = None


class PresetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    is_default: bool = False
    config: PresetPayload


class PresetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    is_default: bool | None = None
    config: PresetPayload | None = None


class PresetMetaResponse(BaseModel):
    id: int
    name: str
    is_default: bool
    description: str | None
    created_at: str
    updated_at: str


class PresetListResponse(BaseModel):
    presets: list[PresetMetaResponse]


class PresetDetailResponse(PresetMetaResponse):
    config: dict | None = None
