"""Diagram phase handlers for the docgen state machine.

The diagram phase sits between ``page.written`` and ``page.reviewed``. It
fans out one ``diagram.requested`` event per ``MermaidPlaceholderBlock``
the writer emitted, runs the diagrammer agent against each, validates the
output through ``mmdc``, and stamps each result back through Redis. Once
every placeholder for a page has resolved (success or graceful Callout
degrade), the aggregator loads the original page from Redis, applies
every diagram/Callout replacement, and emits ``page.diagrams_completed``
so the critic can review the final blocks.

Why Redis instead of ``ctx``
----------------------------
The worker rebuilds ``GenerationContext`` per event from Redis state, so
in-memory ``ctx.pages_in_flight`` does not survive between
``page.written`` (where the page is parsed) and
``diagram.requested`` / ``diagram.completed`` (where it is mutated and
read). Persisting the page + per-placeholder results in Redis lets the
phase work across handler invocations and across worker restarts, and
the SREM/SCARD/SET-NX dance makes the aggregator fire exactly once even
when ``diagram.completed`` events are processed concurrently.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import typing as tp

from source2doc import DocPage
from source2doc.logging import get_logger
from source2doc.mermaid import validate_mermaid
from source2doc.models import docs as doc_models
from source2doc.models.mermaid_kinds import KIND_HINTS

from docgen_core.agents import deps as agent_deps
from docgen_core.agents import diagrammer as diagrammer_agent
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers import metrics as metrics_mod
from docgen_core.workers import runner as agent_runner
from docgen_core.workers.handlers import ingest as ingest_handler


logger = get_logger(__name__)


# Hard cap on diagrams per page — guards against runaway writer output.
# Anything over the cap is degraded to Callout immediately so the page does
# not block the pipeline forever.
MAX_DIAGRAMS_PER_PAGE = 5

# How many times we re-prompt the diagrammer with the previous diagram +
# mmdc stderr before giving up and degrading the placeholder.
MAX_VALIDATE_RETRIES = 2

# Per-generation Redis key TTL. Diagrams within a single generation should
# resolve in minutes, but we keep the keys around for the worker's whole
# generation_state TTL so a restart-mid-phase still finds its tracker.
_TRACKER_TTL_SECONDS = 86400


# ---------------------------------------------------------------------------
# Redis key helpers — all per (generation_id, page_id).
# ---------------------------------------------------------------------------


def _page_key(gen_id: str, page_id: str) -> str:
    return f"diagram:{gen_id}:{page_id}:page"


def _meta_key(gen_id: str, page_id: str) -> str:
    return f"diagram:{gen_id}:{page_id}:meta"


def _pending_key(gen_id: str, page_id: str) -> str:
    return f"diagram:{gen_id}:{page_id}:pending"


def _results_key(gen_id: str, page_id: str) -> str:
    return f"diagram:{gen_id}:{page_id}:results"


def _aggregated_key(gen_id: str, page_id: str) -> str:
    return f"diagram:{gen_id}:{page_id}:aggregated"


def _redis(env: env_mod.DocGenEnv):
    redis = getattr(env, "redis", None)
    if redis is not None:
        return redis
    bus = getattr(env, "event_bus", None)
    inner = getattr(bus, "_redis", None)
    if inner is not None:
        return inner
    raise RuntimeError(
        "diagram handlers require a Redis client on env.redis or env.event_bus._redis"
    )


# ---------------------------------------------------------------------------
# Fan-out: turn a freshly written page into N diagram.requested events
# ---------------------------------------------------------------------------


async def handle_page_written(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    """Inspect placeholders on a freshly-written page and fan out work.

    Stores the page (verbatim) and routing metadata in Redis so the per-
    placeholder handlers can mutate it later. If the writer emitted no
    placeholders this short-circuits straight to ``page.diagrams_completed``.
    """
    generation_id = data["generation_id"]
    page_id = data["page_id"]
    page_data = data["page"]
    page_spec = data["page_spec"]
    repo_id = data.get("repo_id")
    path = data.get("path")
    attempt = data.get("attempt", 1)

    page = DocPage(**page_data)
    placeholders = list(_collect_placeholders(page.blocks))

    # Truncate-and-degrade anything over the cap so an over-eager writer
    # can't pin the pipeline. Excess placeholders are converted to a
    # Callout right here without ever leaving the docgen worker.
    if len(placeholders) > MAX_DIAGRAMS_PER_PAGE:
        logger.warning(
            "diagram_cap_exceeded",
            page_id=page_id,
            requested=len(placeholders),
            cap=MAX_DIAGRAMS_PER_PAGE,
        )
        for excess in placeholders[MAX_DIAGRAMS_PER_PAGE:]:
            _replace_placeholder(
                page.blocks,
                excess.placeholder_id,
                doc_models.CalloutBlock(
                    variant="warning",
                    text=f"Diagram unavailable (cap exceeded): {excess.intent}",
                ),
            )
        placeholders = placeholders[:MAX_DIAGRAMS_PER_PAGE]

    if not placeholders:
        await env.event_bus.emit(
            "page.diagrams_completed",
            {
                "generation_id": generation_id,
                "page_id": page_id,
                "page": page.model_dump(),
                "page_spec": page_spec,
                "repo_id": repo_id,
                "path": path,
                "attempt": attempt,
                "total": 0,
                "succeeded": 0,
                "degraded": 0,
            },
        )
        return

    redis = _redis(env)
    page_key = _page_key(generation_id, page_id)
    meta_key = _meta_key(generation_id, page_id)
    pending_key = _pending_key(generation_id, page_id)
    results_key = _results_key(generation_id, page_id)
    aggregated_key = _aggregated_key(generation_id, page_id)

    # Reset any stale tracker state from a prior worker run for this page.
    await redis.delete(page_key, meta_key, pending_key, results_key, aggregated_key)

    await redis.set(page_key, page.model_dump_json(), ex=_TRACKER_TTL_SECONDS)
    placeholder_ids = [ph.placeholder_id for ph in placeholders]
    await redis.sadd(pending_key, *placeholder_ids)
    await redis.expire(pending_key, _TRACKER_TTL_SECONDS)
    await redis.hset(
        meta_key,
        mapping={
            "page_spec": json.dumps(page_spec),
            "repo_id": repo_id or "",
            "path": path or "",
            "attempt": str(attempt),
            "total": str(len(placeholders)),
        },
    )
    await redis.expire(meta_key, _TRACKER_TTL_SECONDS)

    # In-memory mirror is harmless when present and ignored when absent.
    ctx.page_specs[page_id] = page_spec
    ctx.page_attempts[page_id] = attempt

    logger.info(
        "diagram_fanout",
        page_id=page_id,
        diagrams=len(placeholders),
    )

    for placeholder in placeholders:
        await env.event_bus.emit(
            "diagram.requested",
            {
                "generation_id": generation_id,
                "page_id": page_id,
                "placeholder_id": placeholder.placeholder_id,
                "kind": placeholder.kind,
                "intent": placeholder.intent,
                "anchors": placeholder.anchors,
                "repo_id": repo_id,
                "path": path,
                "attempt": attempt,
            },
        )


# ---------------------------------------------------------------------------
# Per-placeholder agent run + mmdc validation + retry-on-stderr
# ---------------------------------------------------------------------------


async def handle_diagram_requested(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    page_id = data["page_id"]
    placeholder_id = data["placeholder_id"]
    kind = data["kind"]
    intent = data["intent"]
    anchors = list(data.get("anchors") or [])
    repo_id = data.get("repo_id")
    path = data.get("path")

    filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)
    deps = _make_deps(env, filesystem, ctx)
    agent_deps.attach_session_lock(deps, env, "diagrammer")

    # Diagrammer's parallel-run cap is enforced globally inside
    # ``runner.run_agent`` via ``BaseAgentConfig.llm_concurrency`` —
    # writer/critic/planner/etc all share the same semaphore so a
    # diagram fan-out can't starve out a critic mid-pipeline.
    diagram_text, status, reason = await _generate_and_validate(
        env=env,
        deps=deps,
        generation_id=generation_id,
        page_id=page_id,
        placeholder_id=placeholder_id,
        kind=kind,
        intent=intent,
        anchors=anchors,
    )

    await env.event_bus.emit(
        "diagram.completed",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "placeholder_id": placeholder_id,
            "status": status,
            "reason": reason,
            "kind": kind,
            "intent": intent,
            "diagram": diagram_text,
        },
    )


# ---------------------------------------------------------------------------
# Aggregator — collects per-placeholder results in Redis, drains, emits
# page.diagrams_completed exactly once with the mutated page.
# ---------------------------------------------------------------------------


async def handle_diagram_completed(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    page_id = data["page_id"]
    placeholder_id = data["placeholder_id"]
    status = data.get("status", "degraded")
    reason = data.get("reason")
    kind = data.get("kind")
    intent = data.get("intent", "")
    diagram_text = data.get("diagram") or ""

    redis = _redis(env)
    pending_key = _pending_key(generation_id, page_id)
    results_key = _results_key(generation_id, page_id)
    meta_key = _meta_key(generation_id, page_id)
    page_key = _page_key(generation_id, page_id)
    aggregated_key = _aggregated_key(generation_id, page_id)

    await redis.hset(
        results_key,
        placeholder_id,
        json.dumps(
            {
                "status": status,
                "reason": reason,
                "kind": kind,
                "intent": intent,
                "diagram": diagram_text,
            }
        ),
    )
    await redis.expire(results_key, _TRACKER_TTL_SECONDS)
    await redis.srem(pending_key, placeholder_id)
    remaining = await redis.scard(pending_key)

    if remaining > 0:
        return

    claimed = await redis.set(aggregated_key, "1", nx=True, ex=_TRACKER_TTL_SECONDS)
    if not claimed:
        logger.debug(
            "diagram_aggregator_already_claimed",
            page_id=page_id,
        )
        return

    page_json = await redis.get(page_key)
    if not page_json:
        logger.warning("diagrams_completed_page_missing_in_redis", page_id=page_id)
        return

    page = DocPage.model_validate_json(page_json)
    raw_results = await redis.hgetall(results_key)
    succeeded = 0
    degraded = 0
    for ph_id, raw in raw_results.items():
        result = json.loads(raw)
        if result.get("status") == "success":
            new_block: doc_models.DocBlock = doc_models.MermaidBlock(
                diagram=result.get("diagram", "")
            )
            succeeded += 1
        else:
            new_block = doc_models.CalloutBlock(
                variant="warning",
                text=f"Diagram unavailable: {result.get('intent', '')}",
            )
            degraded += 1
        _replace_placeholder(page.blocks, ph_id, new_block)

    meta = await redis.hgetall(meta_key)
    page_spec = json.loads(meta.get("page_spec", "{}"))
    attempt = int(meta.get("attempt", "1") or "1")
    repo_id = meta.get("repo_id") or None
    path = meta.get("path") or None
    total = int(meta.get("total", str(succeeded + degraded)) or "0")

    await env.event_bus.emit(
        "page.diagrams_completed",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "page": page.model_dump(),
            "page_spec": page_spec,
            "repo_id": repo_id,
            "path": path,
            "attempt": attempt,
            "total": total,
            "succeeded": succeeded,
            "degraded": degraded,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_placeholders(
    blocks: list[doc_models.DocBlock],
) -> tp.Iterator[doc_models.MermaidPlaceholderBlock]:
    for _parent, _index, block in doc_models.walk_blocks(blocks):
        if isinstance(block, doc_models.MermaidPlaceholderBlock):
            yield block


def _replace_placeholder(
    blocks: list[doc_models.DocBlock],
    placeholder_id: str,
    new_block: doc_models.DocBlock,
) -> bool:
    for parent, index, block in doc_models.walk_blocks(blocks):
        if (
            isinstance(block, doc_models.MermaidPlaceholderBlock)
            and block.placeholder_id == placeholder_id
        ):
            parent[index] = new_block
            return True
    return False


def _make_deps(
    env: env_mod.DocGenEnv,
    filesystem: tp.Any,
    ctx: ctx_mod.GenerationContext,
) -> agent_deps.DocGenDeps:
    return agent_deps.DocGenDeps(
        embeddings=env.embeddings,
        vectorstore=env.vectorstore,
        chunks_index={},
        event_bus=env.event_bus,
        generation_config=env.config.generation,
        filesystem=filesystem,
        agent_name="diagrammer",
        dominant_language=ctx.dominant_language,
        strict_dedupe=True,
    )


def _build_initial_prompt(kind: str, intent: str, anchors: list[str]) -> str:
    skeleton = KIND_HINTS.get(kind, "")
    anchors_block = "\n".join(f"  - {a}" for a in anchors) if anchors else "  (none)"
    return (
        f"kind: {kind}\n"
        f"intent: {intent}\n"
        f"anchors:\n{anchors_block}\n\n"
        f"Skeleton for kind={kind}:\n{skeleton}\n"
    )


def _build_retry_prompt(
    kind: str,
    intent: str,
    anchors: list[str],
    previous_diagram: str,
    stderr: str,
) -> str:
    base = _build_initial_prompt(kind, intent, anchors)
    return (
        f"{base}\n"
        f"Previous attempt (rejected by mmdc):\n{previous_diagram}\n\n"
        f"mmdc stderr:\n{stderr}\n\n"
        f"Fix the syntax error reported by mmdc. Return the corrected diagram."
    )


async def _generate_and_validate(
    *,
    env: env_mod.DocGenEnv,
    deps: agent_deps.DocGenDeps,
    generation_id: str | None,
    page_id: str,
    placeholder_id: str,
    kind: str,
    intent: str,
    anchors: list[str],
) -> tuple[str, str, str | None]:
    """Run the diagrammer agent in a retry-on-stderr loop.

    Returns ``(diagram_text, status, reason)``. ``status`` is one of
    ``success`` / ``degraded``. On degrade the diagram_text is empty and
    the caller should emit a Callout instead.
    """

    agent, prompt_config = diagrammer_agent.create_diagrammer_agent(
        env.config.resolve_llm("diagrammer"),
        Path(_diagrammer_prompt_path(env)),
        output_language=env.config.generation.output_language,
    )

    prompt = _build_initial_prompt(kind, intent, anchors)
    last_stderr = ""

    for attempt in range(1, MAX_VALIDATE_RETRIES + 1):
        try:
            with metrics_mod.agent_timer() as get_timing:
                result = await agent_runner.run_agent(
                    agent,
                    prompt,
                    deps,
                    "diagrammer",
                    prompt_config,
                    storage=env.storage,
                    pricing=getattr(env, "pricing", None),
                    generation_id=generation_id,
                    page_id=page_id,
                    attempt=attempt,
                )
            await metrics_mod.record_agent_metric(
                env,
                generation_id or "",
                "diagram",
                result,
                timing=get_timing(),
            )
        except Exception as exc:  # noqa: BLE001 - any failure degrades to Callout
            logger.warning(
                "diagrammer_agent_failed",
                page_id=page_id,
                placeholder_id=placeholder_id,
                attempt=attempt,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return "", "degraded", f"agent_error: {type(exc).__name__}"

        output: diagrammer_agent.DiagramOutput = result.output

        if output.notes in ("kind_mismatch", "no_anchors_found"):
            logger.info(
                "diagram_degraded_by_agent",
                page_id=page_id,
                placeholder_id=placeholder_id,
                reason=output.notes,
            )
            return "", "degraded", output.notes

        diagram_text = (output.diagram or "").strip()
        if not diagram_text:
            return "", "degraded", "empty_diagram"

        ok, stderr = await validate_mermaid(diagram_text, kind=output.kind)
        if ok:
            logger.info(
                "diagram_validated",
                page_id=page_id,
                placeholder_id=placeholder_id,
                attempts=attempt,
            )
            return diagram_text, "success", None

        last_stderr = stderr
        logger.warning(
            "diagram_validate_failed",
            page_id=page_id,
            placeholder_id=placeholder_id,
            attempt=attempt,
            stderr=stderr[:500],
        )
        prompt = _build_retry_prompt(kind, intent, anchors, diagram_text, stderr)

    return "", "degraded", f"mmdc_failed: {last_stderr[:200]}"


def ctx_generation_id_from_deps(deps: agent_deps.DocGenDeps) -> str:
    return getattr(deps.event_bus, "channel_id", "") or ""


def _diagrammer_prompt_path(env: env_mod.DocGenEnv) -> str:
    """Resolve the diagrammer prompt path.

    Reads ``env.config.prompts.diagrammer`` if present, otherwise falls
    back to the writer prompt's sibling so an operator who has not added
    the new key still gets a working setup with the default config file.
    """
    prompts = env.config.prompts
    explicit = getattr(prompts, "diagrammer", None)
    if explicit:
        return explicit
    writer_path = Path(prompts.writer)
    return str(writer_path.with_name("diagrammer.yaml"))
