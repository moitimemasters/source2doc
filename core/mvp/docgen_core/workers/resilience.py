import asyncio
import collections.abc as cabc
import typing as tp
from uuid import UUID

import httpx
import openai
import tenacity

from source2doc import errors as errors_lib
from source2doc import logging

from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod


logger = logging.get_logger(__name__)

type HandlerFn = cabc.Callable[
    [env_mod.DocGenEnv, ctx_mod.GenerationContext, dict[str, tp.Any]],
    cabc.Coroutine[tp.Any, tp.Any, None],
]


def _is_step_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors_lib.TransientError):
        return True
    if isinstance(
        exc,
        (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError),
    ):
        return True
    if isinstance(exc, openai.APIStatusError):
        return 500 <= exc.status_code < 600
    # Qdrant / Postgres / any httpx-based client: network-layer errors.
    if isinstance(exc, httpx.TransportError):
        return True
    # ``LLMTimeoutError`` already represents an exhausted retry budget at
    # the HTTP layer — retrying again at the step layer just doubles the
    # wait. Treat it as a terminal failure so the dispatch loop can emit
    # ``reason=llm_timeout`` immediately.
    if isinstance(exc, errors_lib.LLMTimeoutError):
        return False
    return False


def resilient_handler(
    step_name: str,
    max_attempts: int = 3,
    timeout_seconds: int | None = None,
) -> cabc.Callable[[HandlerFn], HandlerFn]:
    """Wrap a pipeline handler with retries and an optional outer timeout.

    ``timeout_seconds=None`` (default) means no outer timeout is applied — safe
    for long-running LLM steps that already guard themselves via ``run_agent``.
    Set an explicit value only for steps with predictable duration (DB/Redis/Qdrant IO).
    """

    def decorator(fn: HandlerFn) -> HandlerFn:
        async def wrapper(
            env: env_mod.DocGenEnv,
            ctx: ctx_mod.GenerationContext,
            data: dict[str, tp.Any],
        ) -> None:
            generation_id = _extract_generation_id(ctx, data)

            try:
                return await _run_with_retry(
                    fn,
                    env,
                    ctx,
                    data,
                    step_name,
                    generation_id,
                    max_attempts,
                    timeout_seconds,
                )
            except Exception as exc:
                await _emit_step_failed(env, generation_id, step_name, exc)
                raise

        return wrapper

    return decorator


async def _run_with_retry(
    fn: HandlerFn,
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
    step_name: str,
    generation_id: UUID | None,
    max_attempts: int,
    timeout_seconds: int | None,
) -> None:
    @tenacity.retry(
        stop=tenacity.stop_after_attempt(max_attempts),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
        retry=tenacity.retry_if_exception(_is_step_retryable),
        before_sleep=_make_before_sleep(step_name, generation_id),
        reraise=True,
    )
    async def _attempt() -> None:
        if timeout_seconds is None:
            await fn(env, ctx, data)
            return
        try:
            async with asyncio.timeout(timeout_seconds):
                await fn(env, ctx, data)
        except TimeoutError:
            logger.warning(
                "step_timeout",
                step_name=step_name,
                generation_id=str(generation_id) if generation_id else None,
                timeout_seconds=timeout_seconds,
            )
            raise

    await _attempt()


def _make_before_sleep(
    step_name: str,
    generation_id: UUID | None,
) -> cabc.Callable:
    async def _before_sleep(retry_state: tenacity.RetryCallState) -> None:
        attempt = retry_state.attempt_number
        exc = retry_state.outcome.exception() if retry_state.outcome else None

        logger.warning(
            "step_retry",
            step_name=step_name,
            generation_id=str(generation_id) if generation_id else None,
            attempt=attempt,
            error=str(exc) if exc else None,
        )

    return _before_sleep


def _extract_generation_id(
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> UUID | None:
    raw = data.get("generation_id") or ctx.generation_id
    if raw:
        return UUID(str(raw))
    return None


async def _emit_step_failed(
    env: env_mod.DocGenEnv,
    generation_id: UUID | None,
    step_name: str,
    exc: Exception,
) -> None:
    if not generation_id:
        return

    payload: dict[str, tp.Any] = {
        "generation_id": str(generation_id),
        "step_name": step_name,
        "error": str(exc),
        "error_type": type(exc).__name__,
        "is_transient": isinstance(exc, errors_lib.TransientError),
    }

    # B9.3 — surface LLM timeouts with a structured ``reason`` so the UI
    # can render a model-specific banner instead of dumping the raw error.
    if isinstance(exc, errors_lib.LLMTimeoutError):
        payload["reason"] = "llm_timeout"
        payload["error_message"] = (
            f"LLM call timed out after {exc.last_attempt_n} attempts ({exc.elapsed_s:.1f} s total)"
        )
        payload["model"] = exc.model
        payload["elapsed_s"] = exc.elapsed_s
        payload["last_attempt_n"] = exc.last_attempt_n
        payload["retry_after"] = None

    try:
        await env.event_bus.emit("step.failed", payload)
    except Exception as emit_err:
        logger.error("step_fail_emit_failed", step_name=step_name, error=str(emit_err))
