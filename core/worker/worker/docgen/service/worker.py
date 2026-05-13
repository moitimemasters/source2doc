import asyncio
import dataclasses as dc
import json
from pathlib import Path
import typing as tp
import uuid

import jinja2
import redis.asyncio as aioredis
import structlog

from source2doc import config as config_lib
from source2doc import storage
from source2doc.events.bus import annotate_event
from source2doc.logging import (
    bind_event,
    bind_generation_context,
    bind_phase,
    bind_pipeline,
    clear_generation_context,
    configure_logging,
)
from source2doc.models.docs import DocPage, PageMetadata
from source2doc.pipelines import DOCGEN

from docgen_core.observability import setup_logfire
from docgen_core.services.embeddings.base import EmbeddingsService
from docgen_core.services.embeddings.openai import OpenAIEmbeddings
from docgen_core.services.vectorstore.base import VectorStoreService
from docgen_core.services.vectorstore.qdrant import QdrantVectorStore
from docgen_core.workers.context import CompletedPage

from worker.config import GatewayWorkerConfig, ModelPricing
from worker.docgen.service import processor as processor_mod
from worker.docgen.service import state as state_mod
from worker.docgen.service import watcher as watcher_mod
from worker.encryption import ConfigEncryption
from worker.streams import consumer as consumer_mod


TASKS_STREAM = "tasks:docgen"
TASKS_CONSUMER_GROUP = "docgen-receivers"
EVENTS_CONSUMER_GROUP = "docgen-processors"


@dc.dataclass
class HandlerEnv:
    config: config_lib.AppConfig
    embeddings: EmbeddingsService
    vectorstore: VectorStoreService
    storage: storage.PostgresStorage
    event_bus: tp.Any
    s3_config: config_lib.S3Config | None
    jinja_env: jinja2.Environment
    pricing: dict[str, ModelPricing] = dc.field(default_factory=dict)
    # Shared Redis client. Handlers that need cross-event coordination
    # (subplan fan-in aggregator) use it for atomic primitives so they don't
    # fight over an in-memory tracker that's rebuilt per event.
    redis: tp.Any = None
    # Worker process id, propagated to ``DocGenDeps.session_worker_id``
    # so the cluster-wide LLM session lock can tag each held slot with
    # the holder. Surfaced by the admin /llm-sessions metric.
    worker_id: str = ""


class DocGenServiceWorker:
    def __init__(self, worker_config: GatewayWorkerConfig):
        self.worker_config = worker_config
        self.worker_id = worker_config.worker_id
        self.encryption = ConfigEncryption(worker_config.encryption_key)
        self.logger = structlog.get_logger(__name__)

        self._initialized = False
        self._running = False
        self.redis: aioredis.Redis | None = None
        self.pg_storage: storage.PostgresStorage | None = None

        self._task_receiver_task: asyncio.Task | None = None
        self._event_processor_task: asyncio.Task | None = None

        # Shared dispatcher semaphore caps in-flight message handlers
        # across BOTH the task-receiver loop (``tasks:docgen``) and the
        # event-processor loop (``events:*``). Without it both consumers
        # default to serial ``await dispatch()`` and the worker grinds
        # one event at a time — which is what was making 4-5 hour bundle
        # generations even on small repos. Real per-LLM-call cap is
        # enforced separately by ``LLMConfig.max_sessions`` (Redis
        # session-lock keyed by sha256(api_key)), so this semaphore can
        # be set well above 5 without 429-cascading.
        self._dispatch_semaphore: asyncio.Semaphore | None = None

    async def async_init(self) -> None:
        if self._initialized:
            return

        configure_logging("INFO")

        _setup_logfire_if_enabled(self.worker_config, self.logger)

        self._dispatch_semaphore = asyncio.Semaphore(
            self.worker_config.worker_concurrency
        )

        self.redis = await aioredis.from_url(
            self.worker_config.redis.url,
            decode_responses=True,
        )

        self.pg_storage = storage.PostgresStorage(self.worker_config.postgres.connection_string)
        await self.pg_storage.connect()

        await consumer_mod.ensure_consumer_group(
            self.redis,
            TASKS_STREAM,
            TASKS_CONSUMER_GROUP,
        )

        self._initialized = True

        self.logger.info(
            "docgen_service_initialized",
            worker_id=self.worker_id,
            tasks_stream=TASKS_STREAM,
        )

    async def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("Worker not initialized. Call async_init() first")

        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        self._running = True

        self.logger.info("docgen_service_started", worker_id=self.worker_id)

        self._task_receiver_task = asyncio.create_task(self._run_task_receiver())
        self._event_processor_task = asyncio.create_task(self._run_event_processor())

        await asyncio.gather(
            self._task_receiver_task,
            self._event_processor_task,
            return_exceptions=True,
        )

    async def stop(self) -> None:
        self.logger.info("stopping_docgen_service", worker_id=self.worker_id)

        self._running = False

        if self._task_receiver_task and not self._task_receiver_task.done():
            self._task_receiver_task.cancel()
            try:
                await asyncio.wait_for(self._task_receiver_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

        if self._event_processor_task and not self._event_processor_task.done():
            self._event_processor_task.cancel()
            try:
                await asyncio.wait_for(self._event_processor_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

        if self.pg_storage:
            await self.pg_storage.close()

        if self.redis:
            await self.redis.aclose()

        self.logger.info("docgen_service_stopped", worker_id=self.worker_id)

    def is_running(self) -> bool:
        return self._running

    async def _run_task_receiver(self) -> None:
        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        self.logger.info("task_receiver_started", stream=TASKS_STREAM)

        await consumer_mod.run_consumer_loop(
            redis=self.redis,
            stream_name=TASKS_STREAM,
            group_name=TASKS_CONSUMER_GROUP,
            consumer_name=self.worker_id,
            handler=self._handle_task_message,
            running=self.is_running,
            block_ms=self.worker_config.redis.block_timeout_ms,
            min_idle_time_ms=self.worker_config.redis.max_idle_time_ms,
            max_retries=self.worker_config.redis.max_retries,
            task_ttl=self.worker_config.redis.stream_ttl_seconds,
            semaphore=self._dispatch_semaphore,
            concurrency=self.worker_config.worker_concurrency,
        )

    async def _run_event_processor(self) -> None:
        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        pattern = f"{self.worker_config.redis.stream_prefix}:*"
        self.logger.info("event_processor_started", pattern=pattern)

        await watcher_mod.watch_streams(
            redis=self.redis,
            pattern=pattern,
            consumer_group=EVENTS_CONSUMER_GROUP,
            consumer_name=self.worker_id,
            handler=self._handle_event_message,
            running=self.is_running,
            scan_interval_seconds=5.0,
            block_ms=self.worker_config.redis.block_timeout_ms,
            min_idle_time_ms=self.worker_config.redis.max_idle_time_ms,
            max_retries=self.worker_config.redis.max_retries,
            task_ttl=self.worker_config.redis.stream_ttl_seconds,
            semaphore=self._dispatch_semaphore,
            concurrency=self.worker_config.worker_concurrency,
        )

    async def _handle_task_message(self, message: consumer_mod.StreamMessage) -> None:
        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        # Refuse to re-process generation.requested for a cancelled gen.
        # Stream redelivery (handler raised → dispatch_message retries up
        # to max_retries=3) can hand us the same task message twice; the
        # second pass would re-emit ``generation.requested`` to the events
        # stream and revive a stop'd pipeline. ``create_state`` is now
        # idempotent (preserves the cancelled flag), but suppressing the
        # emit here is a cleaner short-circuit.
        generation_id = message.data.get("generation_id")
        if generation_id:
            cancel_flag = await self.redis.hget(
                f"state:docgen:{generation_id}", "cancelled"
            )
            if cancel_flag == "true":
                self.logger.info(
                    "skipping_task_message_cancelled",
                    generation_id=generation_id,
                )
                return

        await processor_mod.process_task_message(
            redis=self.redis,
            encryption=self.encryption,
            worker_config=self.worker_config,
            message=message,
        )

    async def _handle_event_message(self, message: consumer_mod.StreamMessage) -> None:
        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        generation_id = message.data.get("generation_id")
        if not generation_id:
            self.logger.warning("event_missing_generation_id", event_type=message.event_type)
            return

        # Pull the per-task trace_id off the event payload so structlog
        # records and downstream emits carry the same correlation token.
        # Legacy events without one get a freshly minted token (warning
        # below) so the chain never silently breaks.
        trace_id = message.data.get("trace_id") if isinstance(message.data, dict) else None
        if not isinstance(trace_id, str) or not trace_id:
            trace_id = uuid.uuid4().hex
            self.logger.warning(
                "event_missing_trace_id",
                event_type=message.event_type,
                generation_id=generation_id,
                minted_trace_id=trace_id,
            )

        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        # Bind as early as possible so *all* logs for this event (including
        # processing_event, postgres connect/close, etc.) are shipped to Redis.
        bind_generation_context(generation_id, self.redis)
        bind_pipeline(DOCGEN.id)
        bind_event(message.message_id)
        bind_phase(DOCGEN.phase_for_event(message.event_type))

        # Drive worker state phase from the registry so phase tracking
        # follows the schema, not whichever handler ran last. Phase is
        # advanced monotonically — parallel page handlers must not flip the
        # indicator back to an earlier stage just because one page raced
        # ahead and emitted a later event.
        target_phase = DOCGEN.target_phase_for_event(message.event_type)
        if target_phase and not target_phase.startswith("_"):
            phase_order = [phase.id for phase in DOCGEN.phases]
            await state_mod.update_phase(
                self.redis,
                generation_id,
                target_phase,
                phase_order=phase_order,
            )

        env: HandlerEnv | None = None
        try:
            self.logger.info(
                "processing_event",
                event_type=message.event_type,
                generation_id=generation_id,
                stream=message.stream_name,
            )

            from docgen_core.workers.handlers import (
                diagram,
                evaluate,
                finalize,
                index,
                ingest,
                normalize,
                plan,
                review,
                subplan,
                write,
            )
            from docgen_core.workers.handlers import incremental as incremental_handler

            handler_map = {
                "generation.requested": ingest.handle,
                "ingest.completed": index.handle,
                "index.completed": plan.handle,
                # Iterative-mode short-circuit: index handler emits
                # ``iterative.index_completed`` when the gateway enqueues
                # with an ``iterative`` envelope. The orchestrator
                # classifies pages, copies unchanged ones, and fans out
                # ``page.write_requested`` for the affected + orphan
                # set — then the standard write→…→finalize chain takes
                # over.
                "iterative.index_completed": incremental_handler.handle,
                # Hierarchical-planner fan-out / aggregator. The top-planner
                # emits ``plan.outline_created``; subplan handlers fan that
                # out to ``subplan.requested`` per section, run subplanners,
                # and finally re-emit ``plan.created`` for the writer.
                "plan.outline_created": subplan.handle_outline_created,
                "subplan.requested": subplan.handle_subplan_requested,
                "subplan.completed": subplan.handle_subplan_completed,
                "plan.created": write.handle_plan,
                "page.write_requested": write.handle_page,
                # Diagram phase between writer and critic. ``page.written``
                # fans out one ``diagram.requested`` per placeholder; the
                # aggregator emits ``page.diagrams_completed`` once all
                # placeholders for a page are resolved.
                "page.written": diagram.handle_page_written,
                "diagram.requested": diagram.handle_diagram_requested,
                "diagram.completed": diagram.handle_diagram_completed,
                "page.diagrams_completed": review.handle,
                "page.reviewed": evaluate.handle,
                "page.revision_requested": write.handle_page,
                # Normalize phase sits between page acceptance and finalize.
                # See docgen_core.workers.handlers.normalize for the rules.
                "page.completed": normalize.handle,
                "page.normalized": finalize.handle,
                "page.failed": finalize.handle_failed,
            }

            unknown_subs = [k for k in handler_map if not DOCGEN.has_event(k)]
            if unknown_subs:
                raise RuntimeError(
                    f"docgen handler_map references events missing from registry: {unknown_subs}"
                )

            handler = handler_map.get(message.event_type)

            if message.event_type == "generation.completed":
                await processor_mod.cleanup_generation(
                    self.redis, generation_id, self.worker_config.redis.stream_prefix
                )
                return

            if not handler:
                return

            # User-initiated stop — skip+ack any in-flight events for the
            # cancelled generation so the worker stops doing more LLM
            # work. Cheap state read (one HGET); the dispatcher above
            # already calls ``state_mod.get_state`` later for context
            # rehydration, but we want to short-circuit BEFORE building
            # the env/agent/etc. Resume clears the flag and re-emits
            # an upstream event to restart the chain.
            cancel_flag = await self.redis.hget(
                f"state:docgen:{generation_id}", "cancelled"
            )
            if cancel_flag == "true":
                self.logger.info(
                    "skipping_event_cancelled",
                    generation_id=generation_id,
                    event_type=message.event_type,
                )
                return

            user_config = await processor_mod.load_config_from_redis(self.redis, generation_id)
            if user_config is None:
                self.logger.error("config_not_found_for_event", generation_id=generation_id)
                return

            app_config = processor_mod.build_app_config(self.worker_config, user_config)

            env = await self._create_handler_env(app_config, generation_id, message.stream_name)

            state = await state_mod.get_state(self.redis, generation_id)
            ctx = _create_context_from_state(state)
            # Snapshot bundle_id before the handler runs; finalize.handle calls ctx.cleanup()
            # which zeroes ctx.bundle_id, so we need the pre-call value as a fallback.
            pre_call_bundle_id = ctx.bundle_id

            await handler(env, ctx, message.data)
            # Persist ctx changes (bundle_id, expected_pages, completed_pages)
            # back to Redis so the next event handler can restore them correctly.
            # Prefer the post-call ctx.bundle_id (set by write.handle_plan), but fall back
            # to the pre-call value when ctx.cleanup() has zeroed it (finalize.handle).
            bundle_id_to_save = ctx.bundle_id if ctx.bundle_id is not None else pre_call_bundle_id
            await _save_context_to_state(self.redis, generation_id, ctx, None, bundle_id_to_save)
        finally:
            # Close storage while context is still bound so close() logs are shipped.
            if env is not None:
                await env.storage.close()
            clear_generation_context()
            # ``dispatch_message`` also clears its own bind on the way out;
            # this matches that pairing for the inner trace_id rebind so the
            # next event in the loop starts from a clean slate.
            structlog.contextvars.clear_contextvars()

    async def _create_handler_env(
        self,
        app_config: config_lib.AppConfig,
        generation_id: str,
        stream_name: str,
    ) -> HandlerEnv:
        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        embeddings = OpenAIEmbeddings(app_config.embeddings)
        vectorstore = QdrantVectorStore(app_config.qdrant, app_config.embeddings.dimensions)
        handler_storage = storage.PostgresStorage(app_config.postgres.connection_string)
        await handler_storage.connect()

        templates_dir = self.worker_config.prompts_dir.parent / "workers" / "prompts"
        if not templates_dir.exists():
            templates_dir = (
                Path(__file__).parent.parent.parent.parent.parent
                / "mvp"
                / "docgen_core"
                / "workers"
                / "prompts"
            )

        jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(templates_dir)),
            autoescape=False,
        )

        event_bus = _StreamEventBus(self.redis, stream_name, generation_id)

        return HandlerEnv(
            config=app_config,
            embeddings=embeddings,
            vectorstore=vectorstore,
            storage=handler_storage,
            event_bus=event_bus,
            s3_config=self.worker_config.s3,
            jinja_env=jinja_env,
            pricing=self.worker_config.pricing,
            redis=self.redis,
            worker_id=self.worker_id,
        )


def _create_context_from_state(
    state: state_mod.GenerationState | None,
) -> tp.Any:
    from docgen_core.workers import context as ctx_mod

    ctx = ctx_mod.GenerationContext()

    if state:
        ctx.generation_id = state.generation_id
        ctx.bundle_id = state.bundle_id
        ctx.expected_pages = state.expected_pages
        ctx.page_attempts = {page_id: ps.attempts for page_id, ps in state.page_states.items()}
        ctx.page_specs = {page_id: ps.spec for page_id, ps in state.page_states.items()}
        ctx.failed_pages = dict(state.failed_pages)
        ctx.dominant_language = state.dominant_language
        ctx.output_language = state.output_language
        # Source-files snapshots produced by ``write.handle_page`` survive
        # across the write → review → normalize → finalize hop only because
        # we round-trip them through Redis state. Without this restore,
        # finalize sees an empty dict and writes ``source_files=NULL``.
        ctx.page_source_files = {
            page_id: list(files) for page_id, files in state.page_source_files.items()
        }
        # Restore completed_pages so is_complete() works correctly across events
        for page_id in state.completed_pages:
            ctx.completed_pages.append(
                CompletedPage(
                    page_id=page_id,
                    page=DocPage(
                        title="",
                        summary="",
                        metadata=PageMetadata(generated_at="", reading_time=0),
                        blocks=[],
                        related=[],
                    ),
                )
            )

    return ctx


async def _save_context_to_state(
    redis: "aioredis.Redis",
    generation_id: str,
    ctx: tp.Any,
    existing_state: state_mod.GenerationState | None,
    bundle_id_override: int | None = None,
) -> None:
    """Persist ctx changes back to Redis state after each handler.

    Uses delta writes against per-page Redis structures (SADD for
    completed, HSET for failed/page_states/source_files) so two handlers
    finishing pages concurrently both win — the previous JSON-blob
    layout had a read-modify-write race that lost completed page_ids
    under ``worker_concurrency > 1``.

    ``bundle_id_override`` is the pre-cleanup snapshot — finalize calls
    ``ctx.cleanup()`` before we save, which zeroes ctx.bundle_id, so we
    fall back to whatever the dispatcher captured before the handler
    ran.
    """
    bundle_id = (
        bundle_id_override if bundle_id_override is not None else ctx.bundle_id
    )

    # Scalars: single HSET, atomic, last-writer-wins is fine because
    # bundle_id / dominant_language are truly set-once in a stable handler
    # (subplan/incremental) and other handlers don't mutate them. Note
    # that ``expected_pages`` is deliberately NOT flushed here — only the
    # planning handlers (subplan, write.handle_plan, incremental) write
    # it via an explicit ``HSET state:docgen:{gen} expected_pages``, so a
    # concurrent stale-ctx handler from the ingest tail can't clobber the
    # planner's count with a zero (which would trip ``is_complete()``
    # after the first page and tear down a half-filled bundle).
    await state_mod.save_scalars(
        redis,
        generation_id,
        bundle_id=bundle_id,
        dominant_language=ctx.dominant_language,
    )

    # Completed pages: SADD is idempotent + atomic — every concurrent
    # handler that finished a page lands its page_id without clobbering
    # anyone else.
    completed_ids = [cp.page_id for cp in ctx.completed_pages]
    if completed_ids:
        completed_key = state_mod._completed_key(generation_id)
        pipe = redis.pipeline()
        pipe.sadd(completed_key, *completed_ids)
        pipe.expire(completed_key, state_mod._DEFAULT_TTL_SECONDS)
        await pipe.execute()

    # Failed pages: HSET per-page (atomic per field).
    if ctx.failed_pages:
        failed_key = state_mod._failed_key(generation_id)
        pipe = redis.pipeline()
        pipe.hset(failed_key, mapping=dict(ctx.failed_pages))
        pipe.expire(failed_key, state_mod._DEFAULT_TTL_SECONDS)
        await pipe.execute()

    # Per-page source files: HSET per-page (atomic per field).
    if ctx.page_source_files:
        source_files_key = state_mod._source_files_key(generation_id)
        serialized = {
            page_id: json.dumps(files)
            for page_id, files in ctx.page_source_files.items()
        }
        pipe = redis.pipeline()
        pipe.hset(source_files_key, mapping=serialized)
        pipe.expire(source_files_key, state_mod._DEFAULT_TTL_SECONDS)
        await pipe.execute()

    # Per-page state (status / attempts / spec): HSET per-page. We
    # write the FULL value of each known page each save — the value
    # for a single page_id is small and last-writer-wins per page is
    # the right semantic (a single page is processed by one handler
    # at a time).
    if ctx.page_attempts:
        page_states_key = state_mod._page_states_key(generation_id)
        page_states_serialized: dict[str, str] = {}
        for page_id, attempts in ctx.page_attempts.items():
            spec = ctx.page_specs.get(page_id, {})
            page_states_serialized[page_id] = json.dumps(
                {"status": "pending", "attempts": attempts, "spec": spec}
            )
        pipe = redis.pipeline()
        pipe.hset(page_states_key, mapping=page_states_serialized)
        pipe.expire(page_states_key, state_mod._DEFAULT_TTL_SECONDS)
        await pipe.execute()


class _StreamEventBus:
    def __init__(self, redis: aioredis.Redis, stream_name: str, generation_id: str):
        self._redis = redis
        self._stream_name = stream_name
        self._generation_id = generation_id
        self._logger = structlog.get_logger(__name__)

    async def emit(self, event_type: str, data: dict) -> None:
        # Hard-stop: handlers that completed AFTER the user clicked stop
        # are normally past the dispatcher's cancel-check (one HGET per
        # event before the handler runs). They keep emitting follow-up
        # events (page.failed, page.written, ...) for ~tens of seconds
        # — the user perceives this as "execution resumed" + the events
        # stream's newest entry stops being ``task.stopped``, so the UI's
        # newest-wins status derivation sees ``page.written`` and reports
        # "running". Suppressing emits here freezes the timeline at
        # ``task.stopped`` immediately. In-flight LLM calls still finish
        # (we don't abort httpx mid-call) but their output never reaches
        # the stream, so no successor handler ever fires. Audit events
        # from the gateway (``task.stopped`` / ``task.resumed``) bypass
        # this bus and xadd directly, so they are unaffected.
        try:
            cancel_flag = await self._redis.hget(
                f"state:docgen:{self._generation_id}", "cancelled"
            )
        except Exception as exc:  # noqa: BLE001
            # Don't block emits on a Redis hiccup — the dispatcher's
            # cancel-check is a second line of defence.
            self._logger.warning(
                "cancel_flag_check_failed", error=str(exc)[:200]
            )
            cancel_flag = None
        if cancel_flag == "true":
            self._logger.info(
                "event_emit_suppressed_cancelled",
                event_type=event_type,
                generation_id=self._generation_id,
            )
            return

        payload: dict[str, tp.Any] = {"generation_id": self._generation_id, **data}
        # Stamp the per-task trace_id on every emitted event so the next
        # consumer can re-bind it without parsing parent payloads. Caller-
        # supplied trace_id (rare) wins so we don't overwrite an explicit
        # override.
        trace_id = consumer_mod.trace_id_from_context()
        if trace_id and "trace_id" not in payload:
            payload["trace_id"] = trace_id
        payload = annotate_event(DOCGEN, event_type, payload, self._logger)
        await consumer_mod.emit_to_stream(
            self._redis,
            self._stream_name,
            event_type,
            payload,
        )

    def subscribe(self, event_type: str, handler: tp.Callable) -> None:
        pass

    def get_events(self) -> list[dict]:
        return []


def _setup_logfire_if_enabled(
    worker_config: GatewayWorkerConfig,
    logger: structlog.stdlib.BoundLogger,
) -> None:
    # Always call setup_logfire — even when disabled it silences pydantic_ai's
    # "Logfire project URL: …" banner that prints on import, so a docker run
    # with logfire.enabled=false produces no logfire stdout chatter.
    try:
        setup_logfire(worker_config.logfire)
    except Exception as e:
        logger.error("logfire_setup_failed", error=str(e), error_type=type(e).__name__)
