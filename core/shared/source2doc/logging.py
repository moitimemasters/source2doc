from contextvars import ContextVar
import logging
import sys
import typing as tp

import structlog


# ContextVar that workers bind before calling handlers.
# When set, the RedisLogProcessor will push log entries to Redis.
_generation_id_var: ContextVar[str | None] = ContextVar("generation_id", default=None)
_redis_client_var: ContextVar[tp.Any] = ContextVar("redis_log_client", default=None)
_phase_var: ContextVar[str | None] = ContextVar("phase", default=None)
_event_id_var: ContextVar[str | None] = ContextVar("event_id", default=None)
_pipeline_id_var: ContextVar[str | None] = ContextVar("pipeline_id", default=None)

LOG_STREAM_PREFIX = "logs"
LOG_STREAM_MAX_LEN = 10_000  # MAXLEN for XADD approximate trimming


def bind_generation_context(generation_id: str, redis_client: tp.Any) -> None:
    """Bind generation_id and redis client to the current async context.

    Call this before invoking a handler so that all structlog calls within
    that handler (and any coroutines it awaits) automatically ship log entries
    to Redis under ``logs:{generation_id}``.
    """
    _generation_id_var.set(generation_id)
    _redis_client_var.set(redis_client)


def clear_generation_context() -> None:
    """Clear the generation context from the current async context."""
    _generation_id_var.set(None)
    _redis_client_var.set(None)
    _phase_var.set(None)
    _event_id_var.set(None)
    _pipeline_id_var.set(None)


def bind_phase(phase: str | None) -> None:
    """Tag every log entry emitted in the current async context with ``phase``."""
    _phase_var.set(phase)


def bind_event(event_id: str | None) -> None:
    """Tag every log entry emitted in the current async context with ``event_id``."""
    _event_id_var.set(event_id)


def bind_pipeline(pipeline_id: str | None) -> None:
    """Tag every log entry emitted in the current async context with ``pipeline_id``."""
    _pipeline_id_var.set(pipeline_id)


def get_phase() -> str | None:
    return _phase_var.get()


def get_event_id() -> str | None:
    return _event_id_var.get()


def get_pipeline_id() -> str | None:
    return _pipeline_id_var.get()


class RedisLogProcessor:
    """structlog processor that ships log entries to Redis Streams.

    The processor is a no-op when no generation_id is bound in the current
    async context, so it is safe to include unconditionally in the processor
    chain.  It never raises — failures are silently swallowed so that logging
    never breaks the application.
    """

    def __call__(
        self,
        logger: tp.Any,
        name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        generation_id = _generation_id_var.get()
        redis_client = _redis_client_var.get()

        if not generation_id or redis_client is None:
            return event_dict

        try:
            import asyncio
            import json

            stream_key = f"{LOG_STREAM_PREFIX}:{generation_id}"

            phase = _phase_var.get()
            event_id = _event_id_var.get()
            pipeline_id = _pipeline_id_var.get()

            # Build a flat dict of string values for XADD
            entry: dict[str, str] = {
                "level": str(event_dict.get("level", "info")),
                "event": str(event_dict.get("event", "")),
                "timestamp": str(event_dict.get("timestamp", "")),
                "logger": str(event_dict.get("_logger", name or "")),
            }
            if phase:
                entry["phase"] = phase
            if event_id:
                entry["event_id"] = event_id
            if pipeline_id:
                entry["pipeline_id"] = pipeline_id

            # Carry over any extra scalar fields as JSON-encoded extras
            extras: dict[str, tp.Any] = {}
            skip = {"level", "event", "timestamp", "_logger", "_record"}
            for k, v in event_dict.items():
                if k not in skip:
                    extras[k] = v
            if extras:
                entry["extras"] = json.dumps(extras, default=str)

            # Fire-and-forget: schedule the coroutine on the running loop.
            # If there is no running loop (e.g. sync context) we skip silently.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_xadd(redis_client, stream_key, entry, LOG_STREAM_MAX_LEN))
            except RuntimeError:
                pass  # No running event loop — skip
        except Exception:
            pass  # Never let logging break the app

        return event_dict


async def _xadd(
    redis_client: tp.Any,
    stream_key: str,
    entry: dict[str, str],
    maxlen: int,
) -> None:
    try:
        await redis_client.xadd(stream_key, entry, maxlen=maxlen, approximate=True)
    except Exception:
        pass


def _console_renderer_with_separator(
    logger: tp.Any,
    name: str,
    event_dict: structlog.types.EventDict,
) -> str:
    renderer = structlog.dev.ConsoleRenderer(
        colors=True,
        exception_formatter=structlog.dev.plain_traceback,
    )
    rendered = renderer(logger, name, event_dict)
    return rendered + "\n"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            RedisLogProcessor(),
            _console_renderer_with_separator,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
