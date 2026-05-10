"""Helpers for persisting per-handler token usage, cost, and timing.

Each docgen handler (planner / writer / critic) calls
:func:`record_agent_metric` immediately after a successful Pydantic-AI
agent run. The function pulls the usage object off the run result,
computes USD cost via the worker pricing map (when available), captures
wall-clock duration, and inserts one row into ``generation_metrics``.

Wall-clock timing is sourced from a ``time.monotonic()`` snapshot the
caller takes before invoking ``agent.run`` (see :func:`agent_timer`).
Wall-clock and ``created_at`` agree to within one DB roundtrip.

Failures are swallowed with a debug log — token bookkeeping must never
sink a real generation. This is on top of Logfire span instrumentation,
not a replacement for it.
"""

from __future__ import annotations

import contextlib
import dataclasses as dc
import datetime as dt
import time
import typing as tp
from uuid import UUID

from source2doc.logging import get_logger


logger = get_logger(__name__)


@dc.dataclass
class StepTiming:
    """Wall-clock + monotonic timestamps for one agent step."""

    started_at: dt.datetime
    completed_at: dt.datetime
    duration_ms: int


@contextlib.contextmanager
def agent_timer() -> tp.Iterator[tp.Callable[[], StepTiming]]:
    """Context manager that yields a getter for the step's timing.

    Used by handlers like::

        with agent_timer() as timing:
            result = await agent.run(...)
        await record_agent_metric(env, gen_id, "plan", result, timing=timing())

    The ``timing`` getter must be called *after* the ``with`` block exits
    so the completed timestamp is final. Calling it inside the block is
    a programming error and raises ``RuntimeError``.
    """
    started_at = dt.datetime.now(dt.UTC)
    started_monotonic = time.monotonic()
    completed: dict[str, StepTiming] = {}

    def _get() -> StepTiming:
        if "value" not in completed:
            raise RuntimeError("agent_timer().get_timing() called before context exit")
        return completed["value"]

    try:
        yield _get
    finally:
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        completed["value"] = StepTiming(
            started_at=started_at,
            completed_at=dt.datetime.now(dt.UTC),
            duration_ms=duration_ms,
        )


def _extract_usage(usage: tp.Any) -> tuple[int, int] | None:
    """Pull (prompt_tokens, completion_tokens) from a pydantic-AI Usage.

    Pydantic-AI renamed ``request_tokens`` / ``response_tokens`` to
    ``input_tokens`` / ``output_tokens`` in 1.x. Older releases used
    ``prompt_tokens`` / ``completion_tokens``. Probe all four names so a
    minor SDK bump doesn't silently zero our counters.
    """
    if usage is None:
        return None

    prompt = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_tokens", None)
        or getattr(usage, "request_tokens", None)
        or 0
    )
    completion = (
        getattr(usage, "output_tokens", None)
        or getattr(usage, "completion_tokens", None)
        or getattr(usage, "response_tokens", None)
        or 0
    )
    if not prompt and not completion:
        return None
    return int(prompt), int(completion)


def _resolve_model_name(env: tp.Any, run_result: tp.Any) -> str:
    """Best-effort model-name extraction.

    Pydantic-AI exposes the resolved model on the run result via
    ``run_result.model`` or via the agent's underlying model — try those
    first, fall back to ``env.config.llm.model``.
    """
    candidates: list[tp.Any] = [
        getattr(run_result, "model", None),
        getattr(run_result, "model_name", None),
        getattr(getattr(run_result, "_model", None), "model_name", None),
    ]
    for cand in candidates:
        if not cand:
            continue
        if isinstance(cand, str):
            return cand
        name = getattr(cand, "model_name", None) or getattr(cand, "name", None)
        if isinstance(name, str):
            return name

    llm_cfg = getattr(getattr(env, "config", None), "llm", None)
    return getattr(llm_cfg, "model", "") or "unknown"


async def record_agent_metric(
    env: tp.Any,
    generation_id: str | UUID,
    step: str,
    run_result: tp.Any,
    timing: StepTiming | None = None,
) -> None:
    """Insert one ``generation_metrics`` row from a Pydantic-AI run result.

    ``run_result`` must expose ``.usage()`` returning a usage-like object
    (input/output token counts). Anything else is silently skipped — this
    is the right behaviour for stub agents in tests.

    ``timing`` is optional: when omitted the duration columns stay NULL
    and the row is excluded from p50/p95 dashboards.
    """
    storage = getattr(env, "storage", None)
    if storage is None or not hasattr(storage, "record_metric"):
        return

    try:
        usage = run_result.usage() if hasattr(run_result, "usage") else None
    except Exception as exc:
        logger.debug(
            "metric_usage_unavailable",
            step=step,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return

    extracted = _extract_usage(usage)
    if extracted is None:
        logger.debug("metric_usage_missing", step=step)
        return

    prompt_tokens, completion_tokens = extracted
    model = _resolve_model_name(env, run_result)

    cost_usd: float | None = None
    pricing = getattr(env, "pricing", None)
    if pricing:
        try:
            from worker.config import compute_cost_usd

            cost_usd = compute_cost_usd(model, prompt_tokens, completion_tokens, pricing)
        except Exception as exc:
            # Pricing computation failure must not crash a real generation.
            logger.debug(
                "metric_cost_compute_failed",
                step=step,
                model=model,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            cost_usd = None

    try:
        gen_uuid = generation_id if isinstance(generation_id, UUID) else UUID(str(generation_id))
        await storage.record_metric(
            generation_id=gen_uuid,
            step=step,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            step_started_at=timing.started_at if timing else None,
            step_completed_at=timing.completed_at if timing else None,
            duration_ms=timing.duration_ms if timing else None,
        )
    except Exception as exc:
        # Treat persistence failures the same as missing usage — log and
        # move on. Metrics are observability, not the critical path.
        logger.debug(
            "metric_record_failed",
            step=step,
            model=model,
            error=str(exc),
            error_type=type(exc).__name__,
        )
