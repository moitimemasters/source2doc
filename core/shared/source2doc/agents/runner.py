from __future__ import annotations

import asyncio
import datetime as dt
import time
import typing as tp
from uuid import UUID

import httpx
import openai
import pydantic_ai
from pydantic_ai import exceptions as pai_exceptions
from pydantic_ai import messages as pai_messages
import tenacity

from source2doc import errors as errors_lib
from source2doc.agents.config import BaseAgentConfig
from source2doc.agents import session_lock as session_lock_mod
from source2doc.llm_retry import llm_http_retry
from source2doc.logging import get_logger


if tp.TYPE_CHECKING:
    from source2doc.storage.postgres import PostgresStorage


logger = get_logger(__name__)


# Process-global semaphore that caps concurrent agent.run invocations
# across the worker. Sized lazily on first call from
# ``BaseAgentConfig.llm_concurrency``; recreated when the size changes
# (different tasks may carry different per-task knobs). Without this
# the worker fires multi-page write/diagram/critic agents in parallel
# up to ``worker_concurrency``, easily exceeding tight provider
# inflight limits (Eliza: 5 → HTTP 429 + cascading degradation).
_LLM_AGENT_SEMAPHORE: asyncio.Semaphore | None = None
_LLM_AGENT_SEMAPHORE_SIZE: int = 0


def _get_agent_semaphore(limit: int) -> asyncio.Semaphore:
    global _LLM_AGENT_SEMAPHORE, _LLM_AGENT_SEMAPHORE_SIZE
    if _LLM_AGENT_SEMAPHORE is None or _LLM_AGENT_SEMAPHORE_SIZE != limit:
        _LLM_AGENT_SEMAPHORE = asyncio.Semaphore(limit)
        _LLM_AGENT_SEMAPHORE_SIZE = limit
    return _LLM_AGENT_SEMAPHORE


class _NoopAsyncContext:
    """Async-context-manager that does nothing.

    Used when the cluster-wide session lock is disabled (no Redis or no
    ``max_sessions``) so the ``async with sem, cluster_lock_cm:`` block
    in run_agent doesn't need a separate code path.
    """

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc_info: tp.Any) -> None:
        return None


def _is_retryable_openai_error(exc: BaseException) -> bool:
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return 500 <= exc.status_code < 600
    return False


def _is_retryable(exc: BaseException) -> bool:
    # ``UsageLimitExceeded`` is intentionally NOT retryable. It fires when
    # an agent burns through ``request_limit`` LLM round-trips on a single
    # page — a runaway tool-call loop, not a transient hiccup. Retrying
    # restarts ``agent.run`` with a fresh budget and multiplies the spend
    # by ``max_attempts``. The cap is the right place to fail fast.
    if isinstance(
        exc,
        (
            TimeoutError,
            pai_exceptions.UnexpectedModelBehavior,
            errors_lib.LLMTransientError,
        ),
    ):
        return True
    return _is_retryable_openai_error(exc)


async def run_agent(
    agent: pydantic_ai.Agent,
    prompt: str,
    deps: tp.Any,
    agent_name: str,
    config: BaseAgentConfig,
    *,
    storage: PostgresStorage | None = None,
    pricing: tp.Mapping[str, tp.Any] | None = None,
    generation_id: str | UUID | None = None,
    page_id: str | None = None,
    section_id: str | None = None,
    attempt: int = 1,
    persist_agent_name: str | None = None,
    trace_id: str | None = None,
) -> tp.Any:
    """Wrap ``agent.run`` with hard timeout, retries and a usage limit.

    Retries cover transient failures: OpenAI connection / timeout / 5xx /
    rate-limit, plus our own ``LLMTransientError`` and Pydantic-AI
    ``UnexpectedModelBehavior``. ``UsageLimitExceeded`` is treated as
    terminal — see ``_is_retryable`` for the reasoning.

    When ``storage`` is supplied the full ``ModelMessage`` list captured
    via ``pydantic_ai.capture_run_messages()`` is persisted to
    ``agent_runs`` on every invocation — success and failure both — so
    the UI can inspect what each agent saw / produced. ``storage=None``
    short-circuits persistence entirely (preserving existing test mocks
    and allowing direct CLI runs of the docgen pipeline).
    """

    async def _before_sleep(retry_state: tenacity.RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "agent_retry",
            agent=agent_name,
            attempt=retry_state.attempt_number,
            error=str(exc) if exc else None,
            error_type=type(exc).__name__ if exc else None,
        )

    # Pull retry budget from the LLM config when present so users can tune
    # it per-task. Defaults match the agent-level retry to keep behaviour
    # unchanged for callers that don't set anything.
    retry_attempts = getattr(config, "retry_max_attempts", None) or config.max_attempts
    retry_total_seconds = getattr(config, "retry_max_total_seconds", None) or float(
        config.timeout_seconds
    )

    # Track the model name + elapsed time so a final timeout can carry
    # rich context up to the worker dispatch loop (B9.3).
    model_name = _get_model_name(agent)
    started_at = time.monotonic()
    started_wall = dt.datetime.now(dt.UTC)

    # Capture every ModelMessage produced inside the run so we can dump
    # it to ``agent_runs`` regardless of whether the run succeeded or
    # exploded. This buffer is shared with the inner _attempt scope —
    # tenacity may invoke _attempt multiple times across retries, but
    # ``capture_run_messages`` is opened *inside* _attempt so each
    # attempt gets its own list (we persist the **last** attempt's
    # messages, since intermediate retries are recorded as ``attempt+N``
    # only when callers bump the kwarg explicitly).
    last_messages_holder: dict[str, list[pai_messages.ModelMessage]] = {"messages": []}

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(config.max_attempts),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        retry=tenacity.retry_if_exception(_is_retryable),
        before_sleep=_before_sleep,
        reraise=True,
    )
    async def _attempt() -> tp.Any:
        logger.info("running_agent", agent=agent_name)
        try:
            async with asyncio.timeout(config.timeout_seconds):
                # HTTP-layer retry (B9.2) sits inside the agent-level retry:
                # transient 5xx / 429 / connection errors are recovered
                # without rebuilding the conversation, while
                # ``UnexpectedModelBehavior`` etc. still trigger a full
                # agent retry one level up.
                @llm_http_retry(
                    max_attempts=retry_attempts,
                    max_total_seconds=retry_total_seconds,
                )
                async def _http_attempt() -> tp.Any:
                    # ``response_tokens_limit=None`` disables the agent-side
                    # cap so a slightly verbose planner/critic doesn't sink
                    # the whole generation. The provider-level ``max_tokens``
                    # is still enforced server-side, and ``request_limit``
                    # still bounds the tool-call loop.
                    usage_kwargs: dict[str, int] = {}
                    if config.request_limit is not None:
                        usage_kwargs["request_limit"] = config.request_limit
                    if config.response_tokens_limit is not None:
                        usage_kwargs["response_tokens_limit"] = (
                            config.response_tokens_limit
                        )
                    # Process-global cap on concurrent agent runs.
                    # Acquire INSIDE the timeout block so the wait time
                    # also counts toward ``timeout_seconds`` — otherwise
                    # a backed-up semaphore would silently inflate the
                    # effective per-attempt budget.
                    sem = _get_agent_semaphore(config.llm_concurrency)
                    # Optional cluster-wide cap via Redis. Pulled off
                    # ``deps`` so each handler can plumb its own per-task
                    # LLMConfig.max_sessions + redis client without
                    # changing run_agent's signature. Falls back to the
                    # process-local asyncio semaphore alone when not
                    # configured.
                    redis_client = getattr(deps, "session_redis", None)
                    api_key_hash = getattr(deps, "session_api_key_hash", None)
                    max_sessions = getattr(deps, "session_max_sessions", None)
                    cluster_lock_cm: tp.AsyncContextManager[tp.Any]
                    if redis_client and api_key_hash and max_sessions:
                        # Tag the lock token with worker_id + agent role so
                        # the admin /llm-sessions metric can show who's
                        # holding each slot at any moment. Falls back to
                        # just agent_name when worker_id isn't plumbed.
                        worker_id = getattr(deps, "session_worker_id", None) or ""
                        label_parts = [
                            p for p in (worker_id, agent_name) if p
                        ]
                        cluster_lock_cm = await session_lock_mod.acquire(
                            redis_client,
                            api_key_hash=api_key_hash,
                            max_sessions=max_sessions,
                            label=":".join(label_parts) if label_parts else None,
                        )
                    else:
                        cluster_lock_cm = _NoopAsyncContext()

                    async with sem, cluster_lock_cm:
                        with pydantic_ai.capture_run_messages() as captured:
                            try:
                                return await agent.run(
                                    prompt,
                                    deps=deps,
                                    usage_limits=pydantic_ai.UsageLimits(**usage_kwargs),
                                )
                            finally:
                                # Refresh the outer holder so the post-run
                                # persistence step sees the latest attempt's
                                # messages even if the call raised.
                                last_messages_holder["messages"] = list(captured)

                result = await _http_attempt()
        except TimeoutError:
            logger.warning(
                "agent_timeout",
                agent=agent_name,
                timeout_seconds=config.timeout_seconds,
            )
            # ``TimeoutError`` stays retryable — surfacing it lets the outer
            # tenacity decorator burn the agent-level retry budget before
            # we declare a permanent timeout (see ``_wrap_terminal_timeout``).
            raise
        logger.info("agent_completed", agent=agent_name)
        return result

    try:
        result = await _attempt()
    except (TimeoutError, httpx.TimeoutException) as exc:
        # B9.3 — only AFTER both the HTTP retry budget and the agent-level
        # retry budget are exhausted do we wrap into a domain-specific
        # error. The worker dispatch loop converts this into a
        # ``step.failed`` event with ``reason='llm_timeout'`` so the UI
        # can render a model-specific banner.
        elapsed = time.monotonic() - started_at
        logger.warning(
            "agent_timeout_final",
            agent=agent_name,
            elapsed_s=elapsed,
            model=model_name,
        )
        wrapped = errors_lib.LLMTimeoutError(
            model=model_name,
            elapsed_s=elapsed,
            last_attempt_n=config.max_attempts,
            cause=exc,
        )
        await _persist_agent_run(
            storage=storage,
            pricing=pricing,
            generation_id=generation_id,
            agent_name=persist_agent_name or agent_name,
            page_id=page_id,
            section_id=section_id,
            attempt=attempt,
            started_wall=started_wall,
            started_monotonic=started_at,
            success=False,
            error=wrapped,
            messages=last_messages_holder["messages"],
            run_result=None,
            model_name=model_name,
            trace_id=trace_id,
        )
        raise wrapped from exc
    except BaseException as exc:
        # All other failures (UsageLimitExceeded, UnexpectedModelBehavior,
        # OpenAI errors that exhausted the retry budget, validation
        # errors, ...) — record + re-raise.
        await _persist_agent_run(
            storage=storage,
            pricing=pricing,
            generation_id=generation_id,
            agent_name=persist_agent_name or agent_name,
            page_id=page_id,
            section_id=section_id,
            attempt=attempt,
            started_wall=started_wall,
            started_monotonic=started_at,
            success=False,
            error=exc,
            messages=last_messages_holder["messages"],
            run_result=None,
            model_name=model_name,
            trace_id=trace_id,
        )
        raise

    await _persist_agent_run(
        storage=storage,
        pricing=pricing,
        generation_id=generation_id,
        agent_name=persist_agent_name or agent_name,
        page_id=page_id,
        section_id=section_id,
        attempt=attempt,
        started_wall=started_wall,
        started_monotonic=started_at,
        success=True,
        error=None,
        messages=last_messages_holder["messages"],
        run_result=result,
        model_name=model_name,
        trace_id=trace_id,
    )
    return result


def _get_model_name(agent: pydantic_ai.Agent) -> str:
    """Best-effort extraction of the underlying model identifier.

    Different Pydantic-AI versions / providers expose the name in slightly
    different shapes; failing soft here keeps the retry/timeout path
    robust against minor SDK churn.
    """

    model = getattr(agent, "model", None)
    if model is None:
        return "unknown"
    name = getattr(model, "model_name", None) or getattr(model, "_model_name", None)
    return str(name) if name else type(model).__name__


def _resolve_model_from_result(run_result: tp.Any, fallback: str) -> str:
    """Pull the resolved model id off an ``AgentRunResult`` when available."""
    if run_result is None:
        return fallback
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
    return fallback


def _extract_usage(usage: tp.Any) -> tuple[int, int, int | None]:
    """Pull ``(input_tokens, output_tokens, request_count)`` from a Usage object.

    Pydantic-AI renamed ``request_tokens`` / ``response_tokens`` to
    ``input_tokens`` / ``output_tokens`` in 1.x; older releases used
    ``prompt_tokens`` / ``completion_tokens``. Probe all three names per
    side so a minor SDK bump doesn't silently zero the counters.
    """
    if usage is None:
        return 0, 0, None
    input_tokens = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_tokens", None)
        or getattr(usage, "request_tokens", None)
        or 0
    )
    output_tokens = (
        getattr(usage, "output_tokens", None)
        or getattr(usage, "completion_tokens", None)
        or getattr(usage, "response_tokens", None)
        or 0
    )
    requests = getattr(usage, "requests", None) or getattr(usage, "request_count", None)
    request_count: int | None = int(requests) if isinstance(requests, int) else None
    return int(input_tokens or 0), int(output_tokens or 0), request_count


def _serialise_messages(messages: tp.Iterable[pai_messages.ModelMessage]) -> list[dict]:
    """Round-trip the captured ``ModelMessage`` list to JSON-native dicts.

    Uses ``ModelMessagesTypeAdapter`` so we get the same shape Pydantic-AI
    itself uses to persist conversations — that buys us a free
    serialisation contract: every minor SDK bump that changes the shape
    is immediately visible as a serialiser failure rather than a silent
    truncation. Falls back to ``str()`` per message on TypeError so a
    single weird message doesn't sink the whole record.
    """
    msg_list = list(messages)
    if not msg_list:
        return []
    try:
        return pai_messages.ModelMessagesTypeAdapter.dump_python(msg_list, mode="json")
    except Exception as exc:
        logger.debug(
            "agent_run_messages_dump_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            count=len(msg_list),
        )
        # Last-resort: stringify each entry so the row is still useful.
        return [{"_repr": repr(m)} for m in msg_list]


def _serialise_output(run_result: tp.Any) -> tp.Any:
    """Coerce ``AgentRunResult.output`` into a JSON-native value."""
    if run_result is None:
        return None
    output = getattr(run_result, "output", None)
    if output is None:
        return None
    if hasattr(output, "model_dump"):
        try:
            return output.model_dump(mode="json")
        except TypeError:
            try:
                return output.model_dump()
            except Exception:
                return repr(output)
    if isinstance(output, (str, int, float, bool, list, dict)) or output is None:
        return output
    return repr(output)


def _compute_cost(
    pricing: tp.Mapping[str, tp.Any] | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Best-effort USD cost lookup mirroring ``docgen_core.workers.metrics``.

    Imports ``compute_cost_usd`` lazily because the worker package isn't
    a hard dependency of ``source2doc.shared`` — the gateway and standalone
    test runs that don't have it installed simply skip the cost column.
    """
    if not pricing:
        return None
    try:
        from worker.config import compute_cost_usd  # noqa: PLC0415 — optional dep
    except Exception:
        return None
    try:
        return compute_cost_usd(model, input_tokens, output_tokens, pricing)
    except Exception as exc:
        logger.debug(
            "agent_run_cost_compute_failed",
            model=model,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


async def _persist_agent_run(
    *,
    storage: PostgresStorage | None,
    pricing: tp.Mapping[str, tp.Any] | None,
    generation_id: str | UUID | None,
    agent_name: str,
    page_id: str | None,
    section_id: str | None,
    attempt: int,
    started_wall: dt.datetime,
    started_monotonic: float,
    success: bool,
    error: BaseException | None,
    messages: tp.Iterable[pai_messages.ModelMessage],
    run_result: tp.Any,
    model_name: str,
    trace_id: str | None,
) -> None:
    """Insert one ``agent_runs`` row. Failures are swallowed (debug-logged).

    Skips the DB write when ``storage`` or ``generation_id`` is missing —
    the runner is also called from CLI / tests where neither is wired.
    """
    if storage is None or generation_id is None:
        return
    if not hasattr(storage, "record_agent_run"):
        return

    try:
        gen_uuid = generation_id if isinstance(generation_id, UUID) else UUID(str(generation_id))
    except (TypeError, ValueError):
        logger.debug("agent_run_persist_bad_generation_id", value=str(generation_id))
        return

    finished_wall = dt.datetime.now(dt.UTC)
    duration_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))

    usage_obj: tp.Any = None
    if run_result is not None and hasattr(run_result, "usage"):
        try:
            usage_obj = run_result.usage()
        except Exception as exc:
            logger.debug(
                "agent_run_usage_unavailable",
                agent=agent_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            usage_obj = None
    input_tokens, output_tokens, request_count = _extract_usage(usage_obj)
    if not input_tokens and not output_tokens:
        # Treat as "unknown" rather than zero so the UI can show a dash.
        input_tokens_val: int | None = None
        output_tokens_val: int | None = None
        total_tokens_val: int | None = None
    else:
        input_tokens_val = input_tokens
        output_tokens_val = output_tokens
        total_tokens_val = input_tokens + output_tokens

    resolved_model = _resolve_model_from_result(run_result, model_name)
    cost_usd = (
        _compute_cost(pricing, resolved_model, input_tokens or 0, output_tokens or 0)
        if (input_tokens_val is not None or output_tokens_val is not None)
        else None
    )

    try:
        await storage.record_agent_run(
            generation_id=gen_uuid,
            agent_name=agent_name,
            page_id=page_id,
            section_id=section_id,
            attempt=attempt,
            started_at=started_wall,
            finished_at=finished_wall,
            duration_ms=duration_ms,
            success=success,
            error_type=type(error).__name__ if error is not None else None,
            error_message=str(error) if error is not None else None,
            request_count=request_count,
            input_tokens=input_tokens_val,
            output_tokens=output_tokens_val,
            total_tokens=total_tokens_val,
            cost_usd=cost_usd,
            messages=_serialise_messages(messages),
            output=_serialise_output(run_result),
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.debug(
            "agent_run_persist_failed",
            agent=agent_name,
            generation_id=str(gen_uuid),
            error=str(exc),
            error_type=type(exc).__name__,
        )
