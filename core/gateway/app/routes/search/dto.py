from typing import Literal

from pydantic import BaseModel, Field


SearchMode = Literal["semantic", "fulltext"]


class SearchFilters(BaseModel):
    file_path: str | None = Field(
        default=None,
        description="Match a specific file path exactly (Qdrant payload `file_path`).",
    )
    directory: str | None = Field(
        default=None,
        description="Prefix-match against the chunk's file_path; e.g. 'src/api/' "
        "returns only chunks under that directory.",
    )
    language: str | None = Field(
        default=None,
        description="Exact match against the language tag the chunker assigned "
        "(e.g. 'python', 'typescript').",
    )


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query text")
    mode: SearchMode = Field(
        default="semantic",
        description="`semantic` runs the embeddings + vector search; `fulltext` "
        "uses Qdrant payload `MatchText` against the chunk content (rank-based score).",
    )
    filters: SearchFilters | None = Field(
        default=None, description="Optional payload filters applied in both modes."
    )
    limit: int = Field(default=20, ge=1, le=100, description="Max results to return.")


class SearchSource(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    language: str | None = None


class SearchMetadata(BaseModel):
    repository_id: str
    chunk_id: str | None = None


class SearchHit(BaseModel):
    text: str
    score: float
    source: SearchSource
    metadata: SearchMetadata


class SearchResponse(BaseModel):
    mode: SearchMode
    total: int
    results: list[SearchHit]
