from pathlib import Path
import typing as tp

import pydantic_ai
from pydantic_ai import exceptions as pai_exceptions

from source2doc import DocPage, storage
from source2doc.logging import get_logger

from docgen_core.agents import critic as critic_agent
from docgen_core.agents import deps as agent_deps
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers import metrics as metrics_mod
from docgen_core.workers import runner as agent_runner
from docgen_core.workers.handlers import ingest as ingest_handler


logger = get_logger(__name__)


_PAGE_TERMINAL_ERRORS: tuple[type[BaseException], ...] = (
    pai_exceptions.UnexpectedModelBehavior,
    pydantic_ai.UsageLimitExceeded,
)


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    page_id = data["page_id"]
    page_data = data["page"]
    page_spec = data["page_spec"]
    repo_id = data.get("repo_id")
    path = data.get("path")
    attempt = data["attempt"]

    logger.info("reviewing_page", page_id=page_id, attempt=attempt)

    page = DocPage(**page_data)

    filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)
    deps = _make_deps(env, filesystem, ctx)
    agent_deps.attach_session_lock(deps, env, "critic")

    prompt = _build_critic_prompt(env, page_spec, page)
    try:
        with metrics_mod.agent_timer() as get_timing:
            review_result = await _run_critic(
                env, deps, prompt, page_id, attempt, generation_id=generation_id
            )
        review = review_result.output
        await metrics_mod.record_agent_metric(
            env, generation_id, "review", review_result, timing=get_timing()
        )
    except _PAGE_TERMINAL_ERRORS as exc:
        # Critic exhausted its retry budget. Treat the page as written-but-
        # unverified and accept it: the writer already produced content,
        # and a missing critic verdict shouldn't sink the whole task.
        logger.warning(
            "page_critic_terminal_failure",
            page_id=page_id,
            attempt=attempt,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        await env.event_bus.emit(
            "page.completed",
            {
                "generation_id": generation_id,
                "page_id": page_id,
                "page": page_data,
                "final_score": 0,
                "review_summary": f"critic_unavailable: {type(exc).__name__}",
            },
        )
        return

    await env.event_bus.emit(
        "page.reviewed",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "page": page_data,
            "page_spec": page_spec,
            "review": review.model_dump(),
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
        agent_name="critic",
        dominant_language=ctx.dominant_language,
        strict_dedupe=True,
    )


def _build_critic_prompt(
    env: env_mod.DocGenEnv,
    page_spec: dict,
    page: DocPage,
) -> str:
    template = env.jinja_env.get_template("critic_review.j2")
    return template.render(
        page_spec=page_spec,
        page_json=page.model_dump_json(indent=2),
    )


async def _run_critic(
    env: env_mod.DocGenEnv,
    deps: agent_deps.DocGenDeps,
    prompt: str,
    page_id: str,
    attempt: int,
    *,
    generation_id: str | None = None,
) -> tp.Any:
    """Run the critic agent and return the raw ``AgentRunResult``.

    The caller pulls ``.output`` for the verdict and ``.usage()`` for the
    token-counting metric record.
    """
    agent, prompt_config = critic_agent.create_critic_agent(
        env.config.resolve_llm("critic"),
        Path(env.config.prompts.critic),
        output_language=env.config.generation.output_language,
    )

    logger.info("running_agent", agent="critic", page_id=page_id, attempt=attempt)
    with pydantic_ai.capture_run_messages() as critic_messages:
        review_result = await agent_runner.run_agent(
            agent,
            prompt,
            deps,
            "critic",
            prompt_config,
            storage=env.storage,
            pricing=getattr(env, "pricing", None),
            generation_id=generation_id,
            page_id=page_id,
            attempt=attempt,
        )
    logger.info(
        "agent_completed",
        agent="critic",
        page_id=page_id,
        messages_count=len(critic_messages),
    )
    return review_result
