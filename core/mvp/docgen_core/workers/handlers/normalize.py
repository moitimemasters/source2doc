"""Normalize handler — runs after a page is accepted, before finalize.

Two-stage pipeline:

1. **Deterministic pre-pass** (always): regex/structure fixes from
   :mod:`source2doc.normalizer.blocks`. Covers the common writer drift
   cases (literal ``## Header`` inside paragraph text, fenced code
   embedded in prose, dead mermaid placeholders).

2. **LLM second-pass** (gated): one round-trip restructuring agent that
   re-emits the same page with cleaner block typing. Triggers when the
   deterministic pass made many edits (``llm_threshold_edits``) or
   ``always_llm`` is set. Falls back silently to the deterministic
   result on any error — losing the LLM pass must not break a generation.
"""

import typing as tp

import pydantic_ai
from pathlib import Path
from pydantic_ai import exceptions as pai_exceptions

from source2doc import DocPage, storage
from source2doc.logging import get_logger
from source2doc.normalizer import normalize_blocks

from docgen_core.agents import deps as agent_deps
from docgen_core.agents import normalizer as normalizer_agent
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers import metrics as metrics_mod
from docgen_core.workers import runner as agent_runner
from docgen_core.workers.handlers import ingest as ingest_handler


logger = get_logger(__name__)


_LLM_TERMINAL_ERRORS: tuple[type[BaseException], ...] = (
    pai_exceptions.UnexpectedModelBehavior,
    pai_exceptions.ModelHTTPError,
    pydantic_ai.UsageLimitExceeded,
)


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    """Normalize ``data['page']`` and re-emit ``page.normalized``.

    Always runs the deterministic pass; the LLM pass is governed by
    ``env.config.normalizer``. The handler **always** ends by emitting
    ``page.normalized`` so the pipeline progresses — even when both
    passes are skipped or the LLM call fails.
    """
    generation_id = data["generation_id"]
    page_id = data["page_id"]
    page_data = data["page"]
    final_score = data.get("final_score", 0)
    review_summary = data.get("review_summary", "")
    repo_id = data.get("repo_id")
    path = data.get("path")

    normalizer_cfg = getattr(env.config, "normalizer", None)
    enabled = bool(getattr(normalizer_cfg, "enabled", True))

    if not enabled:
        await _emit_normalized(
            env,
            generation_id=generation_id,
            page_id=page_id,
            page_data=page_data,
            final_score=final_score,
            review_summary=review_summary,
            deterministic_edits=0,
            llm_used=False,
            llm_status="disabled",
        )
        return

    await env.event_bus.emit(
        "page.normalize_started",
        {"generation_id": generation_id, "page_id": page_id},
    )

    page = DocPage(**page_data)

    fixed_blocks, report = normalize_blocks(list(page.blocks))
    deterministic_edits = report.total

    page = page.model_copy(update={"blocks": fixed_blocks})

    threshold = int(getattr(normalizer_cfg, "llm_threshold_edits", 5))
    always_llm = bool(getattr(normalizer_cfg, "always_llm", False))
    should_run_llm = always_llm or deterministic_edits >= threshold

    llm_used = False
    llm_status = "skipped"

    if should_run_llm:
        try:
            page = await _run_llm_normalizer(
                env,
                ctx,
                page,
                page_id=page_id,
                generation_id=generation_id,
                repo_id=repo_id,
                path=path,
            )
            llm_used = True
            llm_status = "ok"
        except _LLM_TERMINAL_ERRORS as exc:
            # LLM normalize is best-effort — losing it must not block the
            # finalize. The deterministic pass already fixed the worst
            # offenders.
            logger.warning(
                "normalizer_llm_failed",
                page_id=page_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            llm_status = f"failed:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "normalizer_llm_unexpected_error",
                page_id=page_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            llm_status = f"failed:{type(exc).__name__}"

    await _emit_normalized(
        env,
        generation_id=generation_id,
        page_id=page_id,
        page_data=page.model_dump(),
        final_score=final_score,
        review_summary=review_summary,
        deterministic_edits=deterministic_edits,
        llm_used=llm_used,
        llm_status=llm_status,
    )


async def _emit_normalized(
    env: env_mod.DocGenEnv,
    *,
    generation_id: str,
    page_id: str,
    page_data: dict,
    final_score: int,
    review_summary: str,
    deterministic_edits: int,
    llm_used: bool,
    llm_status: str,
) -> None:
    await env.event_bus.emit(
        "page.normalized",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "page": page_data,
            "final_score": final_score,
            "review_summary": review_summary,
            "deterministic_edits": deterministic_edits,
            "llm_used": llm_used,
            "llm_status": llm_status,
        },
    )


async def _run_llm_normalizer(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    page: DocPage,
    *,
    page_id: str,
    generation_id: str,
    repo_id: str | None,
    path: str | None,
) -> DocPage:
    filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)
    deps = _make_deps(env, filesystem, ctx)
    agent_deps.attach_session_lock(deps, env, "normalizer")

    agent, prompt_config = normalizer_agent.create_normalizer_agent(
        env.config.resolve_llm("normalizer"),
        Path(env.config.prompts.normalizer),
        output_language=env.config.generation.output_language,
    )

    prompt = (
        "Нормализуй формат блоков следующей страницы документации. "
        "Содержимое менять нельзя — только переразложить по правильным block-типам.\n\n"
        f"{page.model_dump_json(indent=2)}"
    )

    logger.info("running_agent", agent="normalizer", page_id=page_id)
    with metrics_mod.agent_timer() as get_timing:
        run_result = await agent_runner.run_agent(
            agent,
            prompt,
            deps,
            "normalizer",
            prompt_config,
            storage=env.storage,
            pricing=getattr(env, "pricing", None),
            generation_id=generation_id,
            page_id=page_id,
            attempt=1,
        )
    await metrics_mod.record_agent_metric(
        env, generation_id, "normalize", run_result, timing=get_timing()
    )
    return run_result.output


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
        agent_name="normalizer",
        dominant_language=ctx.dominant_language,
        strict_dedupe=True,
    )
