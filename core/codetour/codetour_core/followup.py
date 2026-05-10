"""Phase B — follow-up step generation for an existing tour.

Given a completed tour and a question anchored at one of its steps, generate
a small batch of new steps that continue the tour. The new steps are
appended to ``CodeTour.steps`` (caller is responsible for persisting).
"""

from __future__ import annotations

import json
import typing as tp
from pathlib import Path

import jinja2

import source2doc.config as config
import source2doc.logging as logging
from source2doc.agents.runner import run_agent
from source2doc.git_context import GitContext
from source2doc.storage import FileSystem

import codetour_core.agents.factory as agent_factory
import codetour_core.agents.deps as agent_deps
import codetour_core.models as models
from codetour_core.config import loader as config_loader
from codetour_core.validator import validate_step


logger = logging.get_logger(__name__)


EventEmitter = tp.Callable[[str, dict], tp.Awaitable[None]]


async def generate_followup(
    tour: models.CodeTour,
    request: models.CodeTourFollowupRequest,
    *,
    llm_config: config.LLMConfig,
    embeddings: tp.Any,
    vectorstore: tp.Any,
    generation_config: config.GenerationConfig,
    prompt_path: Path,
    filesystem: FileSystem | None = None,
    event_emitter: EventEmitter | None = None,
    git_context: GitContext | None = None,
) -> list[models.CodeTourStep]:
    if request.step_index >= len(tour.steps):
        raise ValueError(
            f"step_index={request.step_index} is out of range for tour with "
            f"{len(tour.steps)} steps"
        )

    prompt_config = config_loader.load_prompt(prompt_path)
    if not prompt_config.followup_user_prompt_template:
        raise RuntimeError("Prompt config has no followup_user_prompt_template")

    git_available = False
    if git_context is not None:
        try:
            git_available = await git_context.is_available()
        except Exception:  # noqa: BLE001
            git_available = False

    agent, _ = agent_factory.create_codetour_agent(
        llm_config,
        prompt_path,
        enable_read_file=filesystem is not None,
        enable_git=git_available,
    )

    anchor = tour.steps[request.step_index]
    template = jinja2.Environment().from_string(prompt_config.followup_user_prompt_template)
    user_prompt = template.render(
        original_query=tour.metadata.get("query", ""),
        step_index=request.step_index,
        anchor=anchor.model_dump(),
        existing_steps=[s.model_dump() for s in tour.steps],
        question=request.question,
        max_new_steps=request.max_new_steps,
    )

    deps = agent_deps.CodetourDeps(
        embeddings=embeddings,
        vectorstore=vectorstore,
        filesystem=filesystem,
        generation_config=generation_config,
        agent_name="codetour-followup",
        git_context=git_context if git_available else None,
    )

    result = await run_agent(
        agent,
        user_prompt,
        deps,
        "codetour-followup",
        prompt_config,
    )

    raw = result.output
    parsed = _parse_followup_payload(raw)
    raw_steps = parsed.get("steps") or []

    base_offset = len(tour.steps)
    new_steps: list[models.CodeTourStep] = []

    async def emit(event_type: str, data: dict) -> None:
        if event_emitter is None:
            return
        try:
            await event_emitter(event_type, data)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "codetour_followup_emit_failed",
                event_type=event_type,
                error=str(exc),
            )

    for offset, raw_step in enumerate(raw_steps):
        try:
            step_obj = models.CodeTourStep(**raw_step)
        except Exception as exc:  # noqa: BLE001
            await emit(
                "codetour.followup_step_rejected",
                {"reason": f"schema: {exc}", "raw": raw_step},
            )
            continue

        if filesystem is not None:
            res = await validate_step(
                step_obj,
                filesystem,
                own_index=base_offset + offset,
                total_steps=base_offset + len(raw_steps),
            )
            if not res.is_valid:
                await emit(
                    "codetour.followup_step_rejected",
                    {"reason": res.reason, "step": step_obj.model_dump()},
                )
                continue
            if res.cleaned_step is not None:
                step_obj = res.cleaned_step

        # Always anchor the first new step to the requested step_index if the
        # model didn't add it explicitly.
        if not step_obj.connects_to:
            step_obj = step_obj.model_copy(update={"connects_to": [request.step_index]})

        new_steps.append(step_obj)
        await emit(
            "codetour.followup_step_added",
            {
                "tour_id": str(tour.tour_id),
                "index": base_offset + len(new_steps) - 1,
                "title": step_obj.title,
                "kind": step_obj.kind,
            },
        )

    if not new_steps:
        await emit(
            "codetour.followup_failed",
            {"tour_id": str(tour.tour_id), "reason": "no valid steps were produced"},
        )
        raise RuntimeError("Follow-up agent produced no valid steps")

    return new_steps


def _parse_followup_payload(raw: tp.Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"Unexpected agent output type: {type(raw).__name__}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
        raise
