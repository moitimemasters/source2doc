from pydantic import BaseModel, Field


class RepositoryInfoShort(BaseModel):
    name: str
    source_type: str
    git_url: str | None = None
    git_branch: str | None = None
    commit_sha: str | None = None


class BundleInfo(BaseModel):
    id: int
    generation_id: str
    name: str | None = None
    project_name: str | None = None
    description: str | None = None
    repo_id: str | None = None
    created_at: str
    updated_at: str
    metadata: dict
    pages_count: int
    failed_pages_count: int = 0
    successful_pages_count: int = 0
    repository: RepositoryInfoShort | None = None


class BundleListResponse(BaseModel):
    bundles: list[BundleInfo]


class PageInfo(BaseModel):
    page_id: str
    title: str
    summary: str
    status: str = "completed"
    error: str | None = None
    commit_sha: str | None = None
    created_at: str
    updated_at: str


class PageListResponse(BaseModel):
    pages: list[PageInfo]


# B6.3 / ТЗ ДОК-09 — extra page-detail fields surfaced on GET
# /api/v1/docs/bundles/{generation_id}/pages/{page_id}.
#
# We intentionally keep the existing ``dict`` response shape for backwards
# compatibility with the wiki UI's flexible parsing; this DTO documents
# the new fields and is used by the unit tests as a contract.
class PageMetadataExtras(BaseModel):
    """Additional metadata fields appended by the gateway service layer."""

    generated_at: str | None = None  # ISO 8601, sourced from documentation_pages.updated_at
    llm_model: str | None = None  # most-frequent generation_metrics.model for this generation_id


class PageRepositoryInfo(BaseModel):
    git_url: str | None = None
    commit_sha: str | None = None


class PageDetailResponse(BaseModel):
    """Shape of GET .../pages/{page_id}.

    Used by the test suite as a contract — the route handler still
    returns a plain dict (``page.model_dump()`` plus extras) so the wiki
    UI can keep its loose typing for ``blocks``.
    """

    title: str
    summary: str
    metadata: dict
    blocks: list[dict]
    related: list[str] = []
    repository: PageRepositoryInfo | None = None
    body_markdown: str | None = None  # B6.4 / ТЗ ДОК-10 — raw MD download


# B11.2 / ТЗ ГЕН-08 — append-only page version history.
class PageVersionListItem(BaseModel):
    """One entry in the "Versions" dropdown.

    ``short_sha`` is the 7-char prefix of ``commit_sha`` when present,
    or ``None`` for archive-uploads / pre-B11.1 bundles. The UI uses it
    as the inline label so users don't have to expand long hashes.
    """

    generation_id: str
    commit_sha: str | None = None
    short_sha: str | None = None
    created_at: str


class PageVersionListResponse(BaseModel):
    versions: list[PageVersionListItem]


class PageVersionDetailResponse(BaseModel):
    """Full snapshot returned for a specific historical version.

    Mirrors the latest-page DTO shape closely so the wiki UI can swap
    one for the other when rendering a historical view. The ``blocks``
    field is loosely typed (``list[dict]``) for the same reason
    ``PageDetailResponse.blocks`` is — to avoid pinning the JSON shape
    in the contract.
    """

    page_id: str
    generation_id: str
    commit_sha: str | None = None
    created_at: str
    title: str | None = None
    summary: str | None = None
    metadata: dict | None = None
    blocks: list[dict] = []
    related: list[str] = []
    body_markdown: str | None = None


# B6.2 — cross-page symbol-link index.
class PageSymbol(BaseModel):
    """One entry in the cross-page link index."""

    symbol: str
    page_id: str
    kind: str  # 'page_title' | 'function' | 'class' | 'module'


class PageSymbolsResponse(BaseModel):
    symbols: list[PageSymbol]


# B13.2 / ТЗ АГТ-06 (partial) — page-link graph DTOs.
class PageGraphNode(BaseModel):
    """One node in the wiki link graph — a page that participates in the graph."""

    id: str  # page_id
    title: str | None = None


class PageGraphEdge(BaseModel):
    """One directed edge in the wiki link graph."""

    from_: str = Field(alias="from")
    to: str
    kind: str  # 'symbol' | 'mention' | 'inferred'
    weight: int

    model_config = {"populate_by_name": True}


class PageGraphResponse(BaseModel):
    """Full link graph for a generation. Empty arrays if no edges recorded."""

    nodes: list[PageGraphNode]
    edges: list[PageGraphEdge]


class InboundLink(BaseModel):
    """One row of the "Referenced by …" panel — a page that links *to* us."""

    from_page_id: str
    title: str | None = None
    kind: str
    weight: int


class InboundLinksResponse(BaseModel):
    inbound: list[InboundLink]
