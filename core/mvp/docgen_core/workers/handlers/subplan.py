"""Subplan phase handlers for the hierarchical-planner state machine.

The phase sits between ``plan`` and ``write``. The top-planner produces
``plan.outline_created`` with N section specs; the fan-out handler emits
one ``subplan.requested`` per section; the per-section handler runs the
subplanner agent against a section-scoped scope and emits
``subplan.completed`` with that section's ``page_specs``. Once every
section has completed the aggregator merges the results, creates the
documentation bundle, and emits the original ``plan.created`` event with
the same payload shape downstream handlers (``write_plan``, etc.) already
consume.

State management
----------------
The worker rebuilds ``GenerationContext`` per event from Redis state, so
in-memory aggregation trackers don't survive between handler invocations
and concurrent ``subplan.completed`` events would race against each other.
This phase therefore stores its tracker directly in Redis using atomic
primitives (``SREM`` + ``SCARD`` + ``HSET`` + ``SET NX``) so the aggregator
fires exactly once regardless of concurrency.
"""

from __future__ import annotations

import json
from pathlib import Path
import typing as tp
from uuid import UUID

import pydantic_ai

from source2doc import DocIndex, storage
from source2doc.logging import get_logger

from docgen_core.agents import deps as agent_deps
from docgen_core.agents import subplanner as subplanner_agent
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers import metrics as metrics_mod
from docgen_core.workers import runner as agent_runner
from docgen_core.workers.handlers import ingest as ingest_handler


logger = get_logger(__name__)


# Redis keys per generation. Cleaned up on generation completion.
def _pending_key(gen_id: str) -> str:
    return f"subplan:{gen_id}:pending"


def _results_key(gen_id: str) -> str:
    return f"subplan:{gen_id}:results"


def _meta_key(gen_id: str) -> str:
    return f"subplan:{gen_id}:meta"


def _aggregated_key(gen_id: str) -> str:
    return f"subplan:{gen_id}:aggregated"


_TRACKER_TTL_SECONDS = 86400


# ---------------------------------------------------------------------------
# Fan-out: outline → one subplan.requested per section
# ---------------------------------------------------------------------------


async def handle_outline_created(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    outline = data["outline"]
    repo_id = data.get("repo_id")
    path = data.get("path")
    name = data.get("name")
    description = data.get("description")

    sections: list[dict] = list(outline.get("sections") or [])
    if not sections:
        logger.warning("outline_has_no_sections", generation_id=generation_id)
        return

    redis = _redis(env)

    pending_key = _pending_key(generation_id)
    meta_key = _meta_key(generation_id)
    results_key = _results_key(generation_id)
    aggregated_key = _aggregated_key(generation_id)

    # Reset any stale tracker from a prior run of the same generation_id
    # (resume after worker restart). Then seed the new one.
    await redis.delete(pending_key, meta_key, results_key, aggregated_key)

    section_ids = [s["id"] for s in sections]
    await redis.sadd(pending_key, *section_ids)
    await redis.expire(pending_key, _TRACKER_TTL_SECONDS)

    meta = {
        "sections_json": json.dumps(sections),
        "section_order_json": json.dumps(section_ids),
        "project_summary": outline.get("project_summary", "") or "",
        "repo_id": repo_id or "",
        "path": path or "",
        "name": name or "",
        "description": description or "",
    }
    await redis.hset(meta_key, mapping=meta)
    await redis.expire(meta_key, _TRACKER_TTL_SECONDS)

    logger.info(
        "subplan_fanout",
        generation_id=generation_id,
        sections=len(sections),
    )

    for section in sections:
        await env.event_bus.emit(
            "subplan.requested",
            {
                "generation_id": generation_id,
                "section": section,
                "section_id": section["id"],
                "repo_id": repo_id,
                "path": path,
            },
        )


# ---------------------------------------------------------------------------
# Per-section: run subplanner, emit subplan.completed
# ---------------------------------------------------------------------------


async def handle_subplan_requested(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    section = data["section"]
    section_id = data["section_id"]
    repo_id = data.get("repo_id")
    path = data.get("path")

    logger.info("running_subplanner", section_id=section_id)

    filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)
    deps = _make_deps(env, filesystem, ctx)
    agent_deps.attach_session_lock(deps, env, "subplanner")

    prompt = await _build_prompt(section, filesystem, env)

    agent, prompt_config = subplanner_agent.create_subplanner_agent(
        env.config.resolve_llm("subplanner"),
        Path(_subplanner_prompt_path(env)),
        output_language=env.config.generation.output_language,
    )

    try:
        with (
            metrics_mod.agent_timer() as get_timing,
            pydantic_ai.capture_run_messages(),
        ):
            result = await agent_runner.run_agent(
                agent,
                prompt,
                deps,
                "subplanner",
                prompt_config,
                storage=env.storage,
                pricing=getattr(env, "pricing", None),
                generation_id=generation_id,
                section_id=section_id,
                attempt=1,
            )
        await metrics_mod.record_agent_metric(
            env, generation_id, "subplan", result, timing=get_timing()
        )
        output: subplanner_agent.SubplanOutput = result.output
        page_specs = [ps.model_dump() for ps in output.page_specs]
    except (
        pydantic_ai.UsageLimitExceeded,
        pydantic_ai.exceptions.UnexpectedModelBehavior,
        pydantic_ai.exceptions.ModelHTTPError,
    ) as exc:
        # A weak model can loop on tool calls until ``request_limit`` is
        # exhausted. Don't take the entire generation down — emit an empty
        # ``subplan.completed`` so the aggregator still drains and the
        # writer phase fires for the other sections. The page count for
        # this section will just be 0.
        logger.warning(
            "subplanner_terminal_failure",
            section_id=section_id,
            error=str(exc)[:200],
            error_type=type(exc).__name__,
        )
        page_specs = []

    logger.info(
        "subplanner_completed",
        section_id=section_id,
        pages=len(page_specs),
    )

    await env.event_bus.emit(
        "subplan.completed",
        {
            "generation_id": generation_id,
            "section_id": section_id,
            "page_specs": page_specs,
            "pages_count": len(page_specs),
            "repo_id": repo_id,
            "path": path,
        },
    )


# ---------------------------------------------------------------------------
# Aggregator: drain tracker via Redis atomic ops, emit plan.created once.
# ---------------------------------------------------------------------------


async def handle_subplan_completed(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    section_id = data["section_id"]
    page_specs = list(data.get("page_specs") or [])

    redis = _redis(env)

    results_key = _results_key(generation_id)
    pending_key = _pending_key(generation_id)
    meta_key = _meta_key(generation_id)
    aggregated_key = _aggregated_key(generation_id)

    # Persist this section's result, then drop it from the pending set. SREM +
    # SCARD give us a race-free "am I the last one?" check that works across
    # concurrent handler invocations (worker_concurrency > 1).
    await redis.hset(results_key, section_id, json.dumps(page_specs))
    await redis.expire(results_key, _TRACKER_TTL_SECONDS)
    await redis.srem(pending_key, section_id)
    remaining = await redis.scard(pending_key)

    if remaining > 0:
        return

    # All sections drained — try to claim the aggregator role atomically.
    # SET NX returns truthy only for the first caller, so plan.created is
    # emitted exactly once even if multiple handlers see remaining == 0.
    claimed = await redis.set(aggregated_key, "1", nx=True, ex=_TRACKER_TTL_SECONDS)
    if not claimed:
        logger.debug(
            "subplan_aggregator_already_claimed",
            generation_id=generation_id,
            section_id=section_id,
        )
        return

    meta = await redis.hgetall(meta_key)
    if not meta:
        logger.warning(
            "subplan_aggregator_missing_meta",
            generation_id=generation_id,
        )
        return

    section_order: list[str] = json.loads(meta.get("section_order_json", "[]"))
    sections_raw: list[dict] = json.loads(meta.get("sections_json", "[]"))
    sections_by_id = {s["id"]: s for s in sections_raw}

    raw_results = await redis.hgetall(results_key)
    results_by_section: dict[str, list[dict]] = {
        sid: json.loads(raw) for sid, raw in raw_results.items()
    }

    navigation = _build_navigation(section_order, sections_by_id, results_by_section)
    flat_page_specs = _flatten_page_specs(section_order, results_by_section)

    plan_payload = {
        "navigation": navigation,
        "page_specs": flat_page_specs,
        "project_summary": meta.get("project_summary", ""),
    }

    repo_id = meta.get("repo_id") or None
    path = meta.get("path") or None
    name = meta.get("name") or None
    description = meta.get("description") or None

    project_name = _resolve_project_name(repo_id, path)
    bundle_id = await env.storage.create_bundle(
        UUID(generation_id),
        project_name,
        name=name,
        description=description,
        repo_id=UUID(repo_id) if repo_id else None,
    )
    ctx.bundle_id = bundle_id

    if repo_id:
        try:
            repo_info = await env.storage.get_repository(UUID(repo_id))
        except Exception as exc:
            logger.warning(
                "repo_lookup_failed_for_commit_sha",
                repo_id=repo_id,
                error=str(exc),
            )
            repo_info = None
        ctx.commit_sha = repo_info.commit_sha if repo_info else None
        ctx.repository_id = repo_id
    else:
        ctx.commit_sha = None
        ctx.repository_id = None

    index = DocIndex.create(navigation=navigation)
    await env.storage.write_index(bundle_id, index)

    await env.event_bus.emit(
        "doc.index.created",
        {
            "generation_id": generation_id,
            "bundle_id": bundle_id,
        },
    )

    ctx.expected_pages = len(flat_page_specs)
    ctx.completed_pages.clear()
    for page_spec in flat_page_specs:
        page_id = page_spec["page_id"]
        ctx.page_specs[page_id] = page_spec
        ctx.page_attempts[page_id] = 1

    logger.info(
        "subplan_aggregated",
        generation_id=generation_id,
        sections=len(section_order),
        pages=len(flat_page_specs),
    )

    await env.event_bus.emit(
        "plan.created",
        {
            "generation_id": generation_id,
            "plan": plan_payload,
            "repo_id": repo_id,
            "path": path,
            "name": name,
            "description": description,
        },
    )

    # Tracker keys live for TTL; no need to delete eagerly. The aggregated
    # sentinel guards against double-emit if a duplicate subplan.completed
    # arrives later from a redelivery.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redis(env: env_mod.DocGenEnv):
    redis = getattr(env, "redis", None)
    if redis is not None:
        return redis
    bus = getattr(env, "event_bus", None)
    inner = getattr(bus, "_redis", None)
    if inner is not None:
        return inner
    raise RuntimeError(
        "subplan handlers require a Redis client on env.redis or env.event_bus._redis"
    )


# Per-scope listing cap (subplanner needs more breadth than the top-planner
# but each scope is already narrow; 80 entries gives 240 total for 3 scopes).
_SUBPLAN_LISTING_CAP = 80
_SUBPLAN_FILE_LINE_CAP = 120
_SUBPLAN_SEARCH_LIMIT = 5
_SUBPLAN_SEARCH_CHAR_CAP = 600


async def _build_prompt(
    section: dict,
    filesystem: storage.FileSystem,
    env: env_mod.DocGenEnv,
) -> str:
    seeds: list[str] = list(section.get("search_seeds") or [])
    scopes: list[str] = list(section.get("scope_paths") or [])

    scope_blocks: list[str] = []
    for scope in scopes[:3]:
        scope_blocks.append(await _render_scope(scope, filesystem))

    search_block = await _render_search_seeds(seeds[:3], env)

    scope_dump = "\n\n".join(scope_blocks) if scope_blocks else "  (no scope paths)"
    return (
        "You have the full context for this section below. Do NOT call any "
        "tools — they are not available. Emit a SubplanOutput JSON.\n\n"
        f"<section>\n"
        f"  id: {section['id']}\n"
        f"  title: {section.get('title', '')}\n"
        f"  description: {section.get('description', '')}\n"
        f"</section>\n\n"
        f"<scopes>\n{scope_dump}\n</scopes>\n\n"
        f"<search_results>\n{search_block}\n</search_results>\n\n"
        "Produce 1-4 page_specs that cover this section. page_id MUST start "
        f"with '{section['id']}-' (or be exactly the section id for a single "
        "overview page). Now emit the SubplanOutput JSON."
    )


async def _render_scope(scope: str, filesystem: storage.FileSystem) -> str:
    """Render a single scope_path as a context block (listing or file slice)."""
    try:
        is_file = await filesystem.file_exists(scope)
    except Exception:
        is_file = False

    if is_file:
        try:
            content = await filesystem.read_file(scope)
        except Exception as exc:
            logger.warning("subplan_read_file_failed", scope=scope, error=str(exc))
            return f"<scope path={scope!r}>\n  (read failed: {exc})\n</scope>"
        lines = content.splitlines()
        truncated = len(lines) > _SUBPLAN_FILE_LINE_CAP
        snippet = "\n".join(lines[:_SUBPLAN_FILE_LINE_CAP])
        suffix = "\n... [truncated]" if truncated else ""
        return (
            f"<scope path={scope!r} kind=file lines={len(lines)}>\n"
            f"```\n{snippet}{suffix}\n```\n"
            f"</scope>"
        )

    try:
        entries = await filesystem.list_files(scope, "*")
    except Exception as exc:
        logger.warning("subplan_list_files_failed", scope=scope, error=str(exc))
        return f"<scope path={scope!r}>\n  (list failed: {exc})\n</scope>"
    truncated = len(entries) > _SUBPLAN_LISTING_CAP
    if truncated:
        entries = entries[:_SUBPLAN_LISTING_CAP]
    body = "\n".join(f"    - {p}" for p in entries) if entries else "    (empty)"
    suffix = f"\n    ... [+{_SUBPLAN_LISTING_CAP}+ entries truncated]" if truncated else ""
    return (
        f"<scope path={scope!r} kind=dir count={len(entries)}>\n"
        f"{body}{suffix}\n"
        f"</scope>"
    )


async def _render_search_seeds(
    seeds: list[str],
    env: env_mod.DocGenEnv,
) -> str:
    if not seeds:
        return "  (no search seeds)"

    blocks: list[str] = []
    for seed in seeds:
        seed = seed.strip()
        if not seed:
            continue
        try:
            vec = await env.embeddings.embed_text(seed)
            chunks = await env.vectorstore.search(vec, _SUBPLAN_SEARCH_LIMIT)
        except Exception as exc:
            logger.warning("subplan_search_failed", seed=seed, error=str(exc))
            blocks.append(f"  <seed query={seed!r}>\n    (search failed)\n  </seed>")
            continue

        if not chunks:
            blocks.append(f"  <seed query={seed!r}>\n    (no matches)\n  </seed>")
            continue

        chunk_lines: list[str] = []
        for c in chunks:
            content = c.content
            if len(content) > _SUBPLAN_SEARCH_CHAR_CAP:
                content = content[:_SUBPLAN_SEARCH_CHAR_CAP] + " ..."
            span = c.span
            chunk_lines.append(
                f"    - {span.file_path}:{span.start_line}-{span.end_line}\n"
                f"      {content!r}"
            )
        blocks.append(
            f"  <seed query={seed!r} hits={len(chunks)}>\n"
            + "\n".join(chunk_lines)
            + "\n  </seed>"
        )

    return "\n".join(blocks) if blocks else "  (no search seeds)"


def _build_navigation(
    section_order: list[str],
    sections_by_id: dict[str, dict],
    results_by_section: dict[str, list[dict]],
) -> dict[str, str | dict]:
    navigation: dict[str, str | dict] = {}
    for section_id in section_order:
        section = sections_by_id.get(section_id, {})
        title = section.get("title") or section_id
        page_specs = results_by_section.get(section_id, [])

        single_self_page = (
            len(page_specs) == 1 and page_specs[0]["page_id"] == section_id
        )
        if single_self_page or not page_specs:
            navigation[section_id] = title
        else:
            children: dict[str, str] = {}
            for ps in page_specs:
                children[ps["page_id"]] = ps.get("title") or ps["page_id"]
            navigation[section_id] = {"title": title, "children": children}
    return navigation


def _flatten_page_specs(
    section_order: list[str],
    results_by_section: dict[str, list[dict]],
) -> list[dict]:
    flat: list[dict] = []
    for section_id in section_order:
        flat.extend(results_by_section.get(section_id, []))
    return flat


def _resolve_project_name(repo_id: str | None, path: str | None) -> str:
    if repo_id:
        return repo_id
    if path:
        return Path(path).name
    return "unknown"


def _make_deps(
    env: env_mod.DocGenEnv,
    filesystem: storage.FileSystem,
    ctx: ctx_mod.GenerationContext,
) -> agent_deps.DocGenDeps:
    return agent_deps.DocGenDeps(
        embeddings=env.embeddings,
        vectorstore=env.vectorstore,
        chunks_index={},
        event_bus=env.event_bus,
        generation_config=env.config.generation,
        filesystem=filesystem,
        agent_name="subplanner",
        dominant_language=ctx.dominant_language,
        strict_dedupe=True,
    )


def _subplanner_prompt_path(env: env_mod.DocGenEnv) -> str:
    """Resolve the subplanner prompt path, falling back to the planner's sibling."""
    prompts = env.config.prompts
    explicit = getattr(prompts, "subplanner", None)
    if explicit:
        return explicit
    planner_path = Path(prompts.planner)
    return str(planner_path.with_name("subplanner.yaml"))
