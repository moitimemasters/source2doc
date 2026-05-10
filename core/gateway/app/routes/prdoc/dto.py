"""DTOs for the PR microdoc API (closes ИНТ-02 / ГЕН-06)."""

from __future__ import annotations

import typing as tp
from uuid import UUID

from pydantic import BaseModel, Field

from source2doc.config import EmbeddingsConfig, LLMConfig, QdrantConfig


class PRDocFile(BaseModel):
    """One changed file in a PR diff snapshot.

    The agent works primarily off ``diff``. ``full_content_after`` is a hint
    that lets it ground the explanation in the post-change code; large files
    can omit it to stay under model context limits.
    """

    path: str = Field(..., min_length=1, description="File path relative to repo root.")
    language: str | None = Field(
        default=None,
        description="Language tag (e.g. python, typescript). Used to "
        "fence code blocks in the agent prompt and as a search filter.",
    )
    diff: str = Field(
        ...,
        min_length=1,
        description="Unified diff hunk(s) for the file. Required.",
    )
    full_content_after: str | None = Field(
        default=None,
        description="Optional full file content after the change. Trimmed by the worker.",
    )


class PRDocRequest(BaseModel):
    """Public PR microdoc request — preset-driven LLM/embeddings resolution."""

    repo_id: UUID | None = Field(
        default=None,
        description="Optional repo UUID. When set and a Qdrant collection exists "
        "for it, RAG snippets are fetched per changed file.",
    )
    base_sha: str | None = Field(
        default=None,
        description="Optional base commit SHA, displayed in the rendered summary.",
    )
    head_sha: str | None = Field(
        default=None,
        description="Optional head commit SHA.",
    )
    changed_files: list[PRDocFile] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Changed files in the PR (capped to keep prompts bounded).",
    )
    title: str | None = Field(default=None, description="Optional PR title for context.")
    description: str | None = Field(
        default=None,
        description="Optional PR description / body for context.",
    )


class AdminPRDocRequest(PRDocRequest):
    """Admin variant — may override the preset LLM/embeddings/qdrant configs."""

    preset: str | None = Field(default=None, description="Named preset (default if omitted).")
    llm: LLMConfig | None = Field(default=None)
    embeddings: EmbeddingsConfig | None = Field(default=None)
    qdrant: QdrantConfig | None = Field(default=None)


class PRDocResponse(BaseModel):
    generation_id: UUID
    trace_id: str
    status: str
    message: str


class PRDocResult(BaseModel):
    """Successful result of a completed PR microdoc generation."""

    generation_id: str
    status: str
    summary_markdown: str
    highlights: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    files_summarised: int = 0

    repo_id: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    title: str | None = None

    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class PRDocStatus(BaseModel):
    """Lightweight status payload for an in-progress generation."""

    generation_id: str
    status: tp.Literal["pending", "running", "completed", "failed"]
    error_message: str | None = None
