import dataclasses as dc

from source2doc.config import GenerationConfig
from source2doc.git_context import GitContext
from source2doc.models.chunks import CodeChunk
from source2doc.storage import FileSystem


@dc.dataclass
class CodetourDeps:
    """Dependencies a Code Tour agent receives via ``RunContext.deps``.

    Mirrors the shape of ``DocGenDeps`` so we can reuse the shared
    ``search_code`` / ``read_file`` / ``list_files`` tools verbatim, and adds
    an optional ``git_context`` for the new git-aware tools.
    """

    embeddings: object  # EmbeddingsService
    vectorstore: object  # VectorStoreService
    filesystem: FileSystem | None
    generation_config: GenerationConfig
    agent_name: str = "codetour"
    git_context: GitContext | None = None
    file_cache: dict[str, str] = dc.field(default_factory=dict)
    search_cache: dict[tuple[str, int], list[CodeChunk]] = dc.field(default_factory=dict)
