import collections.abc as cabc
from contextlib import asynccontextmanager
import dataclasses as dc
from pathlib import Path

import jinja2

from source2doc import config, logging, storage
from source2doc.events import bus
from source2doc.pipelines import DOCGEN

from docgen_core.services.embeddings.base import EmbeddingsService
from docgen_core.services.embeddings.openai import OpenAIEmbeddings
from docgen_core.services.vectorstore.base import VectorStoreService
from docgen_core.services.vectorstore.qdrant import QdrantVectorStore
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers import resilience
from docgen_core.workers.handlers import (
    diagram,
    evaluate,
    finalize,
    incremental,
    index,
    ingest,
    normalize,
    plan,
    review,
    subplan,
    write,
)


logger = logging.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "prompts"


@dc.dataclass
class _DocGenEnvImpl:
    config: config.AppConfig
    embeddings: EmbeddingsService
    vectorstore: VectorStoreService
    storage: storage.PostgresStorage
    event_bus: bus.EventBus
    s3_config: config.S3Config | None
    jinja_env: jinja2.Environment


@asynccontextmanager
async def docgen_worker(
    config: config.AppConfig,
    event_bus: bus.EventBus,
    s3_config: config.S3Config | None = None,
    templates_dir: Path | None = None,
) -> cabc.AsyncIterator[env_mod.DocGenEnv]:

    embeddings = OpenAIEmbeddings(config.embeddings)
    vectorstore = QdrantVectorStore(config.qdrant, config.embeddings.dimensions)
    pg_storage = storage.PostgresStorage(config.postgres.connection_string)
    await pg_storage.connect()

    resolved_templates_dir = templates_dir or _TEMPLATES_DIR
    jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(resolved_templates_dir)),
        autoescape=False,
    )

    env = _DocGenEnvImpl(
        config=config,
        embeddings=embeddings,
        vectorstore=vectorstore,
        storage=pg_storage,
        event_bus=event_bus,
        s3_config=s3_config,
        jinja_env=jinja_env,
    )
    ctx = ctx_mod.GenerationContext()

    _register_handlers(event_bus, env, ctx)

    try:
        yield env
    finally:
        await pg_storage.close()


def _register_handlers(
    event_bus: bus.EventBus,
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
) -> None:
    # Predictable I/O-bound steps: safe to cap with an outer timeout.
    wrapped_ingest = resilience.resilient_handler("ingest", max_attempts=3, timeout_seconds=1200)(
        ingest.handle
    )
    wrapped_index = resilience.resilient_handler("index", max_attempts=3, timeout_seconds=1800)(
        index.handle
    )
    wrapped_write_plan = resilience.resilient_handler(
        "write_plan", max_attempts=2, timeout_seconds=300
    )(write.handle_plan)
    wrapped_evaluate = resilience.resilient_handler(
        "evaluate", max_attempts=2, timeout_seconds=300
    )(evaluate.handle)
    wrapped_finalize = resilience.resilient_handler(
        "finalize", max_attempts=3, timeout_seconds=300
    )(finalize.handle)
    # Normalize phase is best-effort: deterministic regex fixes always
    # succeed, the optional LLM second-pass already swallows its own
    # errors. A 600s outer timeout is plenty for the one-round-trip
    # restructure agent under any LLM provider we support.
    wrapped_normalize = resilience.resilient_handler(
        "normalize", max_attempts=2, timeout_seconds=600
    )(normalize.handle)

    # LLM-heavy steps: no outer timeout — duration is governed by
    # AgentConfig.timeout_seconds * max_attempts inside run_agent().
    wrapped_plan = resilience.resilient_handler("plan", max_attempts=3)(plan.handle)
    wrapped_write_page = resilience.resilient_handler("write_page", max_attempts=3)(
        write.handle_page
    )
    wrapped_review = resilience.resilient_handler("review", max_attempts=3)(review.handle)
    wrapped_diagram_fanout = resilience.resilient_handler(
        "diagram_fanout", max_attempts=2, timeout_seconds=120
    )(diagram.handle_page_written)
    wrapped_diagram_request = resilience.resilient_handler(
        "diagram", max_attempts=2, timeout_seconds=600
    )(diagram.handle_diagram_requested)
    wrapped_diagram_aggregator = resilience.resilient_handler(
        "diagram_aggregate", max_attempts=2, timeout_seconds=60
    )(diagram.handle_diagram_completed)
    # Hierarchical-planner fan-out / fan-in. Outline + aggregator are cheap
    # bookkeeping, so they get a tight outer timeout. Per-section subplanner
    # runs are LLM-heavy — leave them governed by AgentConfig only.
    wrapped_subplan_fanout = resilience.resilient_handler(
        "subplan_fanout", max_attempts=2, timeout_seconds=60
    )(subplan.handle_outline_created)
    wrapped_subplan_request = resilience.resilient_handler(
        "subplan", max_attempts=3
    )(subplan.handle_subplan_requested)
    wrapped_subplan_aggregate = resilience.resilient_handler(
        "subplan_aggregate", max_attempts=2, timeout_seconds=120
    )(subplan.handle_subplan_completed)
    # Iterative-mode orchestrator. Cheap I/O (postgres reads, page copies,
    # event fan-out) — no LLM calls of its own, so a tight outer timeout
    # is fine.
    wrapped_iterative = resilience.resilient_handler(
        "iterative", max_attempts=2, timeout_seconds=300
    )(incremental.handle)

    handler_map: dict[str, cabc.Callable] = {
        "generation.requested": wrapped_ingest,
        "ingest.completed": wrapped_index,
        "index.completed": wrapped_plan,
        "iterative.index_completed": wrapped_iterative,
        "plan.outline_created": wrapped_subplan_fanout,
        "subplan.requested": wrapped_subplan_request,
        "subplan.completed": wrapped_subplan_aggregate,
        "plan.created": wrapped_write_plan,
        "page.write_requested": wrapped_write_page,
        "page.written": wrapped_diagram_fanout,
        "diagram.requested": wrapped_diagram_request,
        "diagram.completed": wrapped_diagram_aggregator,
        "page.diagrams_completed": wrapped_review,
        "page.reviewed": wrapped_evaluate,
        "page.revision_requested": wrapped_write_page,
        "page.completed": wrapped_normalize,
        "page.normalized": wrapped_finalize,
    }

    unknown = [event_type for event_type in handler_map if not DOCGEN.has_event(event_type)]
    if unknown:
        raise RuntimeError(
            f"docgen handler subscriptions reference events missing from the registry: {unknown}"
        )

    for event_type, handler_fn in handler_map.items():
        event_bus.subscribe(
            event_type,
            lambda data, fn=handler_fn: fn(env, ctx, data),
        )
