import dataclasses as dc

from source2doc.models import docs as doc_models


type PageId = str
type SectionId = str


@dc.dataclass
class CompletedPage:
    page_id: PageId
    page: doc_models.DocPage


@dc.dataclass
class DiagramTracker:
    """Per-page bookkeeping for the diagram fan-out/fan-in phase."""

    pending: set[str] = dc.field(default_factory=set)
    total: int = 0
    succeeded: int = 0
    degraded: int = 0


@dc.dataclass
class GenerationContext:
    generation_id: str = ""
    bundle_id: int | None = None
    expected_pages: int = 0
    completed_pages: list[CompletedPage] = dc.field(default_factory=list)
    failed_pages: dict[PageId, str] = dc.field(default_factory=dict)
    page_attempts: dict[PageId, int] = dc.field(default_factory=dict)
    page_specs: dict[PageId, dict] = dc.field(default_factory=dict)
    pending_diagrams: dict[PageId, DiagramTracker] = dc.field(default_factory=dict)
    # NB: subplan fan-in tracker lives in Redis (see workers/handlers/subplan.py)
    # so concurrent ``subplan.completed`` events don't race on an in-memory
    # dict the worker rebuilds per event.
    pages_in_flight: dict[PageId, doc_models.DocPage] = dc.field(default_factory=dict)
    # Per-page set of repo-relative file paths the writer touched (via
    # read_file or as search_code hits). Captured at write-time and read
    # back at finalize-time to populate ``documentation_pages.source_files``,
    # which the iterative-mode classifier later uses to figure out which
    # pages a ``changed_files`` set affects. Sorted for deterministic
    # persistence.
    page_source_files: dict[PageId, list[str]] = dc.field(default_factory=dict)
    dominant_language: str = "text"
    # Natural-language locale chosen at task-creation time. Plumbed into
    # every agent's prompt so writer / planner / subplanner / critic /
    # diagrammer / normalizer all render in the same language. Defaults
    # to "en" so legacy generations without the field keep their old
    # output language.
    output_language: str = "en"
    # Captured once at plan-time from the repositories row so each
    # write_page call can stamp the source revision (B11.1 / ГЕН-08).
    commit_sha: str | None = None
    # B11.2 / ТЗ ГЕН-08 — pinned alongside ``commit_sha`` so each
    # ``page_versions`` row also records the source repository, letting
    # reverse-lookups ("which versions of a page came from this repo")
    # work without joining through ``documentation_bundles``.
    repository_id: str | None = None
    # Per-task correlation token bound by the gateway (B3.3 / EVT-01).
    # Plumbed onto handlers so log lines that bypass structlog contextvars
    # (e.g. inside Pydantic-AI's callback hooks) can still be correlated.
    trace_id: str = ""

    def record_page(self, page_id: PageId, page: doc_models.DocPage) -> None:
        self.completed_pages.append(CompletedPage(page_id=page_id, page=page))

    def record_failed_page(self, page_id: PageId, reason: str) -> None:
        self.failed_pages[page_id] = reason

    def is_complete(self) -> bool:
        return (len(self.completed_pages) + len(self.failed_pages)) >= self.expected_pages

    def cleanup(self) -> None:
        self.completed_pages.clear()
        self.failed_pages.clear()
        self.page_attempts.clear()
        self.page_specs.clear()
        self.pending_diagrams.clear()
        self.page_source_files.clear()
        self.bundle_id = None
        self.expected_pages = 0
        self.dominant_language = "text"
        self.output_language = "en"
        self.commit_sha = None
        self.repository_id = None
        self.trace_id = ""
