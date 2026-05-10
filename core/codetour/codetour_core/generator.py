from __future__ import annotations

import datetime as dt
import json
import typing as tp
from pathlib import Path

import jinja2

import source2doc.config as config
import source2doc.logging as logging
import source2doc.storage.codetour as codetour_storage
from source2doc.agents.runner import run_agent
from source2doc.git_context import GitContext
from source2doc.storage import FileSystem

import codetour_core.agents.factory as agent_factory
import codetour_core.agents.deps as agent_deps
import codetour_core.models as models
from codetour_core.validator import validate_step


logger = logging.get_logger(__name__)


EventEmitter = tp.Callable[[str, dict], tp.Awaitable[None]]


class CodetourGenerator:
    def __init__(
        self,
        llm_config: config.LLMConfig,
        embeddings: tp.Any,
        vectorstore: tp.Any,
        storage: codetour_storage.CodetourStorage,
        prompt_path: Path,
        generation_config: config.GenerationConfig,
        filesystem: FileSystem | None = None,
        event_emitter: EventEmitter | None = None,
        git_context: GitContext | None = None,
    ):
        self.llm_config = llm_config
        self.embeddings = embeddings
        self.vectorstore = vectorstore
        self.storage = storage
        self.prompt_path = prompt_path
        self.generation_config = generation_config
        self.filesystem = filesystem
        self.event_emitter = event_emitter
        self.git_context = git_context
        self.jinja_env = jinja2.Environment()

    async def generate(self, request: models.CodeTourGenerationRequest) -> models.CodeTour:
        logger.info(
            "generating_codetour",
            tour_id=str(request.tour_id),
            generation_id=str(request.generation_id),
            qdrant_collection=request.qdrant_collection,
        )

        git_available = False
        if self.git_context is not None:
            try:
                git_available = await self.git_context.is_available()
            except Exception:  # noqa: BLE001
                git_available = False

        agent, prompt_config = agent_factory.create_codetour_agent(
            self.llm_config,
            self.prompt_path,
            enable_read_file=self.filesystem is not None,
            enable_git=git_available,
        )

        user_prompt = self._render_user_prompt(prompt_config.user_prompt_template, request)

        deps = agent_deps.CodetourDeps(
            embeddings=self.embeddings,
            vectorstore=self.vectorstore,
            filesystem=self.filesystem,
            generation_config=self.generation_config,
            agent_name="codetour",
            git_context=self.git_context if git_available else None,
        )

        tour_data, steps = await self._run_with_retry(
            agent, user_prompt, deps, prompt_config
        )

        tour = models.CodeTour(
            tour_id=request.tour_id,
            generation_id=request.generation_id,
            title=tour_data.get("title") or request.query,
            description=tour_data.get("description") or "",
            steps=steps,
            created_at=dt.datetime.now(dt.UTC),
            metadata={
                "qdrant_collection": request.qdrant_collection,
                "max_steps": request.max_steps,
                "query": request.query,
                "mode": request.mode,
            },
        )

        logger.info(
            "codetour_generated",
            tour_id=str(tour.tour_id),
            generation_id=str(request.generation_id),
            steps_count=len(tour.steps),
        )

        return tour

    async def _emit(self, event_type: str, data: dict) -> None:
        if self.event_emitter is None:
            return
        try:
            await self.event_emitter(event_type, data)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "codetour_emit_failed",
                event_type=event_type,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def _render_user_prompt(
        self,
        template_text: str,
        request: models.CodeTourGenerationRequest,
    ) -> str:
        template = self.jinja_env.from_string(template_text)
        return template.render(
            query=request.query,
            generation_id=str(request.generation_id),
            qdrant_collection=request.qdrant_collection,
            max_steps=request.max_steps,
            context_files=request.context_files,
            mode=request.mode,
        )

    async def _run_with_retry(
        self,
        agent: tp.Any,
        user_prompt: str,
        deps: tp.Any,
        prompt_config: tp.Any,
    ) -> tuple[dict[str, tp.Any], list[models.CodeTourStep]]:
        """Run the agent and validate the steps it returns; rerun once with
        feedback if every step failed schema/filesystem validation.

        The codetour agent emits free-form JSON, so step validation happens
        downstream of the LLM. When schema rejects every step we used to
        silently land an empty tour. Now we feed the validation errors back
        into the next call so the agent can fix its output before we give up.
        """
        max_attempts = 2
        last_rejected: list[str] = []
        tour_data: dict[str, tp.Any] = {}
        steps: list[models.CodeTourStep] = []
        for attempt in range(1, max_attempts + 1):
            prompt = user_prompt
            if last_rejected:
                feedback = "\n".join(f"- {r}" for r in last_rejected[:5])
                prompt = (
                    f"{user_prompt}\n\n"
                    "Your previous attempt failed schema validation for every step. "
                    "Common errors below — fix them and emit a fresh tour JSON.\n"
                    f"{feedback}"
                )
            result = await run_agent(agent, prompt, deps, "codetour", prompt_config)
            tour_data = self._parse_tour_result(result.output)
            raw_steps = tour_data.get("steps", []) or []
            steps, rejected = await self._build_steps_collecting_rejections(raw_steps)
            if steps or not raw_steps or attempt == max_attempts:
                return tour_data, steps
            last_rejected = rejected
            logger.warning(
                "codetour_retry_after_validation",
                attempt=attempt,
                rejected_count=len(rejected),
            )
        return tour_data, steps

    async def _build_steps_collecting_rejections(
        self,
        raw_steps: list[dict[str, tp.Any]],
    ) -> tuple[list[models.CodeTourStep], list[str]]:
        """Wrapper around ``_build_steps`` that also returns the rejection
        reasons collected along the way.

        We reuse the existing ``_build_steps`` logic by intercepting its
        emission of ``codetour.step_rejected`` events through ``_emit``.
        """
        rejections: list[str] = []
        original_emit = self._emit

        async def collecting_emit(event_type: str, data: dict) -> None:
            if event_type == "codetour.step_rejected":
                reason = data.get("reason", "unknown")
                rejections.append(str(reason))
            await original_emit(event_type, data)

        self._emit = collecting_emit  # type: ignore[assignment]
        try:
            steps = await self._build_steps(raw_steps)
        finally:
            self._emit = original_emit  # type: ignore[assignment]
        return steps, rejections

    def _parse_tour_result(self, result_data: tp.Any) -> dict[str, tp.Any]:
        if isinstance(result_data, dict):
            return result_data
        if not isinstance(result_data, str):
            raise ValueError(f"Unexpected agent output type: {type(result_data).__name__}")
        try:
            return json.loads(result_data)
        except json.JSONDecodeError:
            start = result_data.find("{")
            end = result_data.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(result_data[start:end])
            raise

    async def _build_steps(
        self,
        raw_steps: list[dict[str, tp.Any]],
    ) -> list[models.CodeTourStep]:
        steps: list[models.CodeTourStep] = []
        total_raw = len(raw_steps)
        for idx, raw in enumerate(raw_steps):
            try:
                step_obj = models.CodeTourStep(**raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "codetour_step_skipped",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    raw=raw,
                )
                await self._emit(
                    "codetour.step_rejected",
                    {"reason": f"schema: {exc}", "raw": raw},
                )
                continue

            if self.filesystem is not None:
                result = await validate_step(
                    step_obj,
                    self.filesystem,
                    own_index=idx,
                    total_steps=total_raw,
                )
                if not result.is_valid:
                    logger.warning(
                        "codetour_step_invalid",
                        reason=result.reason,
                        file=step_obj.file,
                    )
                    await self._emit(
                        "codetour.step_rejected",
                        {"reason": result.reason, "step": step_obj.model_dump()},
                    )
                    continue
                if result.cleaned_step is not None:
                    step_obj = result.cleaned_step
                if result.line_drift:
                    await self._emit(
                        "codetour.step_line_drift",
                        {
                            "file": step_obj.file,
                            "claimed_line": step_obj.line,
                        },
                    )

            steps.append(step_obj)
            await self._emit(
                "codetour.step_added",
                {
                    "index": len(steps) - 1,
                    "title": step_obj.title,
                    "kind": step_obj.kind,
                    "file": step_obj.file,
                    "line": step_obj.line,
                    "key_idea": step_obj.key_idea,
                    "highlights_count": len(step_obj.highlights),
                },
            )

        return steps
