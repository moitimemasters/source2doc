from pathlib import Path
import typing as tp

import pydantic_ai

from source2doc import storage
from source2doc.logging import get_logger

from docgen_core.agents import deps as agent_deps
from docgen_core.agents import planner as planner_agent
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers import metrics as metrics_mod
from docgen_core.workers import runner as agent_runner
from docgen_core.workers.handlers import ingest as ingest_handler


logger = get_logger(__name__)


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    repo_id = data.get("repo_id")
    path = data.get("path")
    name = data.get("name")
    description = data.get("description")

    target_display = repo_id if repo_id else path
    logger.info("starting_top_planning", target=target_display)

    filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)
    deps = _make_deps(env, filesystem, ctx)
    agent_deps.attach_session_lock(deps, env, "planner")

    with metrics_mod.agent_timer() as get_timing:
        plan_result = await _run_planner(
            env, deps, target_display, generation_id=generation_id
        )

    await metrics_mod.record_agent_metric(
        env, generation_id, "plan", plan_result, timing=get_timing()
    )

    outline: planner_agent.PlanOutline = plan_result.output
    await _emit_outline_created(
        env,
        generation_id,
        outline,
        repo_id,
        path,
        name,
        description,
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
        agent_name="planner",
        dominant_language=ctx.dominant_language,
        # qwen3-coder-style models loop on identical tool calls and burn
        # request_limit before emitting structured output. Hard-stop them.
        strict_dedupe=True,
    )


async def _run_planner(
    env: env_mod.DocGenEnv,
    deps: agent_deps.DocGenDeps,
    target_display: str | None,
    *,
    generation_id: str | None = None,
) -> tp.Any:
    """Run the tool-free top-planner.

    Pre-fetches the top-level listing + README content (if present) from the
    filesystem, embeds both in the user prompt, then runs the agent which
    only emits ``PlanOutline``. No tool calls = no looping on weak models.
    """
    agent, prompt_config = planner_agent.create_planner_agent(
        env.config.resolve_llm("planner"),
        Path(env.config.prompts.planner),
        output_language=env.config.generation.output_language,
    )

    prompt = await _build_planner_prompt(deps.filesystem)

    logger.info("running_agent", agent="planner", target=target_display)
    with pydantic_ai.capture_run_messages() as planner_messages:
        plan_result = await agent_runner.run_agent(
            agent,
            prompt,
            deps,
            "planner",
            prompt_config,
            storage=env.storage,
            pricing=getattr(env, "pricing", None),
            generation_id=generation_id,
            attempt=1,
        )
    logger.info("agent_completed", agent="planner", messages_count=len(planner_messages))

    return plan_result


# Hard caps on context size to keep the planner prompt small. The outline
# only needs the top-level shape of the repo, not deep listings.
_PLANNER_LISTING_CAP = 200
_PLANNER_README_CHAR_CAP = 8000
# Depth-2 drill-down: pick the top-N subdirs (by listing order) and inline
# their immediate contents. Keeps the prompt rich enough to suggest 6-12
# sections for a non-trivial repo without ballooning context size.
_PLANNER_SUBDIR_LIMIT = 8
_PLANNER_PER_SUBDIR_ENTRIES = 25
_README_CANDIDATES = (
    "README.md",
    "README.rst",
    "README.txt",
    "README",
    "readme.md",
    "Readme.md",
)


def _looks_like_directory(entry: str) -> bool:
    """Heuristic: top-level entries without a file extension and without
    a leading dot (.git, .github, ...) are treated as directories worth
    drilling into. Cheap and avoids an extra ``stat`` round-trip per entry.
    """
    name = entry.rstrip("/")
    if not name or name.startswith("."):
        return False
    base = name.split("/")[-1]
    if "." in base:
        return False
    return True


async def _build_planner_prompt(filesystem: storage.FileSystem) -> str:
    """Pre-fetch repo structural data and assemble the user prompt.

    Returns a self-contained prompt the agent can answer without any tool
    access. Tolerates missing READMEs and empty filesystems.
    """
    top_files: list[str]
    try:
        top_files = await filesystem.list_files(".", "*")
    except Exception as exc:
        logger.warning("planner_list_files_failed", error=str(exc))
        top_files = []

    truncated = False
    if len(top_files) > _PLANNER_LISTING_CAP:
        truncated = True
        top_files = top_files[:_PLANNER_LISTING_CAP]

    listing_block = "\n".join(f"  - {p}" for p in top_files) if top_files else "  (empty)"
    if truncated:
        listing_block += f"\n  ... [+{_PLANNER_LISTING_CAP}+ entries truncated]"

    readme_block = "(no README found)"
    for candidate in _README_CANDIDATES:
        if candidate not in top_files and not any(
            f.lower() == candidate.lower() for f in top_files
        ):
            continue
        try:
            content = await filesystem.read_file(candidate)
        except Exception as exc:
            logger.warning(
                "planner_read_readme_failed",
                file_path=candidate,
                error=str(exc),
            )
            continue
        if len(content) > _PLANNER_README_CHAR_CAP:
            content = content[:_PLANNER_README_CHAR_CAP] + "\n... [README truncated]"
        readme_block = f"```\n{content}\n```"
        break

    subdir_blocks: list[str] = []
    drilled = 0
    for entry in top_files:
        if drilled >= _PLANNER_SUBDIR_LIMIT:
            break
        if not _looks_like_directory(entry):
            continue
        try:
            inner = await filesystem.list_files(entry, "*")
        except Exception as exc:
            logger.warning(
                "planner_subdir_listing_failed",
                directory=entry,
                error=str(exc),
            )
            continue
        if not inner:
            continue
        capped = inner[:_PLANNER_PER_SUBDIR_ENTRIES]
        more = len(inner) - len(capped)
        body = "\n".join(f"    - {p}" for p in capped)
        if more > 0:
            body += f"\n    ... [+{more} more]"
        subdir_blocks.append(f"  {entry}/\n{body}")
        drilled += 1
    subdir_section = (
        "\n".join(subdir_blocks) if subdir_blocks else "  (no subdirectories drilled)"
    )

    return (
        "You have the full structural context below. Do NOT call any tools — "
        "they are not available. Emit a PlanOutline JSON describing 6-12 "
        "documentation sections.\n\n"
        f"<top_level_listing count={len(top_files)}>\n"
        f"{listing_block}\n"
        f"</top_level_listing>\n\n"
        f"<subdirectory_listings drilled={drilled}>\n"
        f"{subdir_section}\n"
        f"</subdirectory_listings>\n\n"
        f"<readme>\n{readme_block}\n</readme>\n\n"
        "Now emit the PlanOutline JSON. Aim for broad coverage: include "
        "sections for configuration, testing, deployment, and any specialized "
        "subsystems visible in the listings."
    )


async def _emit_outline_created(
    env: env_mod.DocGenEnv,
    generation_id: str,
    outline: planner_agent.PlanOutline,
    repo_id: str | None,
    path: str | None,
    name: str | None,
    description: str | None,
) -> None:
    await env.event_bus.emit(
        "plan.outline_created",
        {
            "generation_id": generation_id,
            "outline": outline.model_dump(),
            "section_count": len(outline.sections),
            "repo_id": repo_id,
            "path": path,
            "name": name,
            "description": description,
        },
    )
