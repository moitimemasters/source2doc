from pathlib import Path
import typing as tp
import uuid

import jinja2
import pydantic_ai
from pydantic_ai import exceptions as pai_exceptions

from source2doc import storage
from source2doc.logging import get_logger
from source2doc.models import docs as doc_models
from source2doc.models import review as review_models

from docgen_core.agents import deps as agent_deps
from docgen_core.agents import writer as writer_agent
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers import metrics as metrics_mod
from docgen_core.workers import runner as agent_runner
from docgen_core.workers.handlers import ingest as ingest_handler


logger = get_logger(__name__)


# Errors that mean the writer agent gave up on this page after exhausting
# its own retry budget. They MUST be isolated per page — letting them bubble
# would crash the whole task via the consumer's catch-all.
_PAGE_TERMINAL_ERRORS: tuple[type[BaseException], ...] = (
    pai_exceptions.UnexpectedModelBehavior,
    pai_exceptions.ModelHTTPError,  # 4xx from provider (e.g. context-length 400)
    pydantic_ai.UsageLimitExceeded,
)


async def handle_plan(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    """Fan out one ``page.write_requested`` per ``page_spec`` from the plan.

    Bundle creation, ``doc.index.created``, and ``ctx.page_specs`` priming
    happen earlier in the subplan aggregator (``handle_subplan_completed``).
    By the time this handler runs, ``ctx.bundle_id`` and ``ctx.expected_pages``
    are already populated; this handler only emits the per-page work events.
    """
    generation_id = data["generation_id"]
    plan_data = data["plan"]
    repo_id = data.get("repo_id")
    path = data.get("path")

    page_specs = plan_data["page_specs"][: env.config.generation.max_nodes]

    logger.info("plan_created", pages_count=len(page_specs))

    # The aggregator already populated ctx.expected_pages / ctx.page_specs /
    # ctx.page_attempts and created the bundle. Re-cap expected_pages here so
    # the max_nodes truncation is reflected.
    ctx.expected_pages = len(page_specs)

    for page_spec in page_specs:
        await env.event_bus.emit(
            "page.write_requested",
            {
                "generation_id": generation_id,
                "page_spec": page_spec,
                "repo_id": repo_id,
                "path": path,
                "attempt": 1,
            },
        )


async def handle_page(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    page_spec = data["page_spec"]
    repo_id = data.get("repo_id")
    path = data.get("path")
    attempt = data.get("attempt", 1)

    page_id = page_spec["page_id"]
    logger.info("writing_page", page_id=page_id, attempt=attempt)

    filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)
    deps = _make_deps(env, filesystem, ctx)
    agent_deps.attach_session_lock(deps, env, "writer")

    preloaded_files = await _preload_primary_files(
        filesystem,
        deps,
        page_spec.get("primary_files") or [],
    )

    prompt = _build_prompt(
        env.jinja_env,
        page_spec,
        attempt,
        data.get("previous_review"),
        ctx.dominant_language,
        iterative_update=data.get("iterative_update"),
        preloaded_files=preloaded_files,
    )

    try:
        with metrics_mod.agent_timer() as get_timing:
            page_result = await _run_writer(
                env, deps, prompt, page_id, attempt, generation_id=generation_id
            )
        page = page_result.output
        await metrics_mod.record_agent_metric(
            env, generation_id, "write", page_result, timing=get_timing()
        )
        # Writer prompt requires at least one mermaid_placeholder per page,
        # but weak code-models (qwen3-coder) skip placeholders despite the
        # instruction. Inject a default overview placeholder so the diagram
        # phase actually fires; if anchors don't resolve, the diagrammer
        # gracefully degrades to a Callout.
        _ensure_diagram_placeholder(page, page_spec, page_id)
        # Capture which files this writer-run grounded on. Read first from
        # the page's own ``metadata.source_refs`` (the writer is asked to
        # populate these for B6.5 deep-links) and union with everything the
        # tools touched. Persisted by ``finalize.handle`` into
        # ``documentation_pages.source_files`` for the iterative classifier.
        touched: set[str] = set(deps.touched_files)
        for ref in page.metadata.source_refs or []:
            if ref.file_path:
                touched.add(ref.file_path)
        ctx.page_source_files[page_id] = sorted(touched)
    except _PAGE_TERMINAL_ERRORS as exc:
        # Writer has exhausted its tool/agent retry budget for this page.
        # Emit page.failed so finalize can record it and the rest of the
        # pages keep going. Do NOT re-raise — that would trigger the
        # consumer's catch-all and emit task.failed for the whole stream.
        logger.warning(
            "page_writer_terminal_failure",
            page_id=page_id,
            attempt=attempt,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        await env.event_bus.emit(
            "page.failed",
            {
                "generation_id": generation_id,
                "page_id": page_id,
                "page_spec": page_spec,
                "phase": "write",
                "attempt": attempt,
                "error": str(exc) or type(exc).__name__,
                "error_type": type(exc).__name__,
            },
        )
        return

    await env.event_bus.emit(
        "page.written",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "page": page.model_dump(),
            "page_spec": page_spec,
            "repo_id": repo_id,
            "path": path,
            "attempt": attempt,
        },
    )


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
        agent_name="writer",
        dominant_language=ctx.dominant_language,
        # qwen3-coder-class models loop on identical (search_code, read_file)
        # calls and burn ``request_limit`` before emitting a DocPage. The
        # strict dedup tool-wrappers raise ModelRetry on a duplicate call,
        # which forces the model to either rephrase or emit final output.
        strict_dedupe=True,
    )


def _ensure_diagram_placeholder(
    page: doc_models.DocPage,
    page_spec: dict,
    page_id: str,
) -> None:
    """Inject a default mermaid placeholder if the writer skipped them all.

    qwen3-coder-class models routinely ignore the prompt's "must include 1+
    mermaid_placeholder" directive. Without a placeholder the diagram phase
    short-circuits and the page ends up flat. We append one placeholder with
    a generic intent + the page's search_queries as anchors. The diagrammer
    grounds on those anchors via search_code; if none resolve, it returns a
    Callout fallback so the page never blocks on a bad anchor.
    """
    has_placeholder = any(
        isinstance(b, doc_models.MermaidPlaceholderBlock)
        for _parent, _index, b in doc_models.walk_blocks(page.blocks)
    )
    if has_placeholder:
        return

    title = page.title or page_id
    anchors = list(page_spec.get("search_queries") or [])[:3]
    page.blocks.append(
        doc_models.MermaidPlaceholderBlock(
            placeholder_id=str(uuid.uuid4()),
            kind="flowchart",
            intent=f"High-level architecture diagram for {title}.",
            anchors=anchors,
        )
    )
    logger.info(
        "writer_placeholder_injected",
        page_id=page_id,
        anchors=anchors,
    )


_PRELOAD_MAX_FILES = 4
_PRELOAD_MAX_LINES_PER_FILE = 200


async def _preload_primary_files(
    filesystem: storage.FileSystem,
    deps: agent_deps.DocGenDeps,
    primary_files: list[str],
) -> list[dict[str, tp.Any]]:
    """Read subplanner-identified primary files and seed writer state.

    The writer agent normally has to discover relevant files via
    search_code/read_file; on weak models that turns into a 30+ round-trip
    loop. By reading those files once at prompt-build time and embedding
    them in the user prompt we cut the writer's tool budget by ~70%.

    Side effects on ``deps``:
    - ``file_cache`` is populated so any stray ``read_file`` from the
      writer returns immediately without hitting S3.
    - ``tool_call_log`` is seeded with the (path, no-range) call key so
      the FIRST repeat read_file of a preloaded file already raises
      ModelRetry — the model gets immediate feedback that the content is
      already in front of it.
    - ``touched_files`` records the paths so iterative-mode classifier
      sees the page grounded on these files.

    Each file is capped to ``_PRELOAD_MAX_LINES_PER_FILE`` to keep the
    initial user prompt bounded; the writer can still ranged-read for
    the rest. Missing/binary files are skipped silently — never an error.
    """
    preloaded: list[dict[str, tp.Any]] = []
    if not primary_files:
        return preloaded
    for path in primary_files[:_PRELOAD_MAX_FILES]:
        try:
            if not await filesystem.file_exists(path):
                logger.info("preload_skip_missing", path=path)
                continue
            content = await filesystem.read_file(path)
        except UnicodeDecodeError:
            logger.info("preload_skip_binary", path=path)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("preload_failed", path=path, error=str(exc)[:200])
            continue

        lines = content.splitlines()
        total_lines = len(lines)
        truncated = total_lines > _PRELOAD_MAX_LINES_PER_FILE
        snippet = (
            "\n".join(lines[:_PRELOAD_MAX_LINES_PER_FILE]) if truncated else content
        )

        deps.file_cache[f"writer:{path}"] = content
        deps.tool_call_log.add(f"writer:read_file:{path}:None:None")
        touched: set[str] | None = getattr(deps, "touched_files", None)
        if touched is not None:
            touched.add(path)

        preloaded.append(
            {
                "path": path,
                "content": snippet,
                "truncated": truncated,
                "total_lines": total_lines,
            }
        )
    logger.info(
        "primary_files_preloaded",
        count=len(preloaded),
        paths=[f["path"] for f in preloaded],
    )
    return preloaded


def _build_prompt(
    jinja_env: jinja2.Environment,
    page_spec: dict,
    attempt: int,
    previous_review: dict | None,
    dominant_language: str = "text",
    *,
    iterative_update: dict | None = None,
    preloaded_files: list[dict[str, tp.Any]] | None = None,
) -> str:
    # Iterative-mode update branch. Only used by the iterative handler when
    # rewriting a base-bundle page — never the initial full-mode flow. The
    # prompt is given the prior body verbatim plus the diffs of the files
    # this page references; the writer agent should preserve unchanged
    # sections and patch only what the diff invalidates.
    if iterative_update is not None and attempt == 1:
        import json as _json

        template = jinja_env.get_template("writer_iterative_update.j2")
        return template.render(
            title=page_spec["title"],
            description=page_spec["description"],
            search_queries=page_spec.get("search_queries") or [],
            dominant_language=dominant_language,
            prior_body_json=_json.dumps(iterative_update.get("prior_body") or {}, indent=2),
            changed_files=iterative_update.get("changed_files") or [],
        )

    if attempt == 1:
        template = jinja_env.get_template("writer_initial.j2")
        return template.render(
            title=page_spec["title"],
            description=page_spec["description"],
            search_queries=page_spec["search_queries"],
            dominant_language=dominant_language,
            preloaded_files=preloaded_files or [],
        )

    review = review_models.CriticOutput(**previous_review) if previous_review else None
    template = jinja_env.get_template("writer_revision.j2")
    return template.render(
        attempt=attempt,
        title=page_spec["title"],
        description=page_spec["description"],
        review=review,
        dominant_language=dominant_language,
    )


async def _run_writer(
    env: env_mod.DocGenEnv,
    deps: agent_deps.DocGenDeps,
    prompt: str,
    page_id: str,
    attempt: int,
    *,
    generation_id: str | None = None,
) -> tp.Any:
    """Run the writer agent and return the raw ``AgentRunResult``.

    The caller pulls ``.output`` for the DocPage and ``.usage()`` for the
    token-counting metric record.
    """
    agent, prompt_config = writer_agent.create_writer_agent(
        env.config.resolve_llm("writer"),
        Path(env.config.prompts.writer),
        output_language=env.config.generation.output_language,
    )

    logger.info("running_agent", agent="writer", page_id=page_id, attempt=attempt)
    with pydantic_ai.capture_run_messages() as writer_messages:
        page_result = await agent_runner.run_agent(
            agent,
            prompt,
            deps,
            "writer",
            prompt_config,
            storage=env.storage,
            pricing=getattr(env, "pricing", None),
            generation_id=generation_id,
            page_id=page_id,
            attempt=attempt,
        )
    logger.info(
        "agent_completed",
        agent="writer",
        page_id=page_id,
        messages_count=len(writer_messages),
    )
    return page_result
