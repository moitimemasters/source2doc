import dataclasses as dc
import typing as tp
import uuid

from source2doc.config import GenerationConfig
from source2doc.events.bus import EventBus
from source2doc.models.chunks import CodeChunk
from source2doc.storage import FileSystem

from docgen_core.services.embeddings.base import EmbeddingsService
from docgen_core.services.vectorstore.base import VectorStoreService


@dc.dataclass
class DocGenDeps:
    embeddings: EmbeddingsService
    vectorstore: VectorStoreService
    chunks_index: dict[str, CodeChunk]
    event_bus: EventBus
    generation_config: GenerationConfig
    filesystem: FileSystem
    agent_name: str = "unknown"
    # Best-effort tag of the repo's dominant programming language (set from
    # ingest stats). Tools and prompts use it to anchor agents to the actual
    # codebase instead of leaning on a Python-shaped training prior.
    dominant_language: str = "text"
    # Short id stamped on every tool log line so a user can prove from the
    # log stream that two ``cache_hit`` events belong to the same in-flight
    # agent run (vs accidentally shared state). Unique per ``DocGenDeps``
    # instance, which is exactly one ``agent.run`` invocation.
    invocation_id: str = dc.field(default_factory=lambda: uuid.uuid4().hex[:8])
    # Per-run caches. Populated lazily by tools to avoid redundant S3 reads /
    # Qdrant queries when the agent calls the same tool with the same args.
    # Keys are namespaced by ``agent_name`` (see tools/{files,search}.py) so
    # any future refactor that accidentally shares deps across agent types
    # still cannot collide on cache lookups.
    file_cache: dict[str, str] = dc.field(default_factory=dict)
    search_cache: dict[tuple[str, str, int], list[CodeChunk]] = dc.field(default_factory=dict)
    # When True, tools raise ModelRetry on the SECOND identical (tool, args)
    # re-invocation; subsequent dups return the cached value silently with
    # a hint instead. Two-state dedupe avoids burning the per-tool retry
    # budget when weak models stubbornly re-call the same args > twice.
    strict_dedupe: bool = False
    # Canonicalised "agent:tool:args" strings invoked at least once this run.
    tool_call_log: set[str] = dc.field(default_factory=set)
    # Subset of ``tool_call_log`` that has already been ModelRetry-warned;
    # third and subsequent dup calls fall back to silent cached return.
    tool_call_warned: set[str] = dc.field(default_factory=set)
    # Repo-relative file paths the agent reached during this run — populated
    # by ``read_file`` (direct reads) and by ``search_code`` (each hit's
    # ``file_path``). The writer handler reads this after a successful page
    # generation and persists it as ``documentation_pages.source_files``
    # so the iterative classifier can later answer "which pages reference
    # file X" via the ``source_files && ARRAY[...]`` overlap operator.
    touched_files: set[str] = dc.field(default_factory=set)
    # Optional cluster-wide session-lock parameters. When all three are
    # set, ``runner.run_agent`` acquires a Redis-backed semaphore keyed
    # by ``session_api_key_hash`` before each LLM call. Each handler
    # populates these from ``env.config.resolve_llm(role)`` —
    # ``max_sessions=None`` falls back to the per-process asyncio
    # semaphore alone, which is the legacy behaviour.
    session_redis: tp.Any = None
    session_api_key_hash: str | None = None
    session_max_sessions: int | None = None
    # Worker process id, copied off env on each handler invocation so
    # the runner can tag session-lock tokens with it for the admin
    # metrics endpoint (``/api/v1/admin/llm-sessions``).
    session_worker_id: str | None = None


def attach_session_lock(deps: "DocGenDeps", env: tp.Any, role: str) -> "DocGenDeps":
    """Populate session-lock fields on ``deps`` from ``env`` + per-role LLM.

    Reads the redis client off ``env`` (handles both ``env.redis``
    direct-attribute and ``env.event_bus._redis`` legacy paths). Reads
    ``LLMConfig.max_sessions`` + ``api_key`` via
    ``env.config.resolve_llm(role)``. When any required piece is
    missing, leaves the fields ``None`` so ``runner.run_agent`` falls
    back to its in-process asyncio semaphore.
    """
    from source2doc.agents.session_lock import hash_api_key

    redis = getattr(env, "redis", None)
    if redis is None:
        bus = getattr(env, "event_bus", None)
        redis = getattr(bus, "_redis", None)
    if redis is None:
        return deps

    config = getattr(env, "config", None)
    resolve = getattr(config, "resolve_llm", None) if config is not None else None
    if not callable(resolve):
        return deps
    try:
        llm = resolve(role)
    except Exception:  # noqa: BLE001 — defensive (role not present, etc.)
        return deps

    max_sessions = getattr(llm, "max_sessions", None)
    api_key = getattr(llm, "api_key", None)
    if not max_sessions or not api_key:
        return deps

    deps.session_redis = redis
    deps.session_api_key_hash = hash_api_key(api_key)
    deps.session_max_sessions = max_sessions
    # Pull worker_id off env when available (production worker sets it
    # on HandlerEnv); CLI / tests may not, in which case the lock just
    # gets tagged with the agent role only.
    deps.session_worker_id = getattr(env, "worker_id", None) or getattr(
        getattr(env, "config", None), "worker_id", None
    )
    return deps
