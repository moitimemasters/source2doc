import asyncio
import collections.abc as cabc
import typing as tp

from source2doc.logging import get_logger
from source2doc.pipelines.types import Pipeline


class EventBus(tp.Protocol):
    async def emit(self, event_type: str, data: dict) -> None: ...
    def subscribe(self, event_type: str, handler: cabc.Callable) -> None: ...
    def get_events(self) -> list[dict]: ...


def annotate_event(
    pipeline: Pipeline | None,
    event_type: str,
    data: dict,
    logger: tp.Any | None = None,
) -> dict:
    """Stamp ``phase`` and ``kind`` onto ``data`` from the pipeline registry.

    A no-op when pipeline is None or event isn't registered (logs a warning
    so handler-emitted strings that drift from the registry get caught).
    """
    if pipeline is None:
        return data
    if not pipeline.has_event(event_type):
        if logger is not None:
            logger.warning(
                "event_not_in_pipeline",
                event_type=event_type,
                pipeline=pipeline.id,
            )
        return data
    ev = pipeline.event(event_type)
    enriched = dict(data)
    enriched.setdefault("phase", ev.phase)
    enriched.setdefault("kind", ev.kind.value)
    return enriched


class SimpleEventBus:
    def __init__(self, pipeline: Pipeline | None = None) -> None:
        self._events: list[dict] = []
        self._handlers: dict[str, cabc.Callable] = {}
        self.pipeline = pipeline
        self.logger = get_logger(__name__)

    async def emit(self, event_type: str, data: dict) -> None:
        data = annotate_event(self.pipeline, event_type, data, self.logger)
        event = {
            "type": event_type,
            "data": data,
        }
        self._events.append(event)
        self.logger.info("event_emitted", event_type=event_type)

        handler = self._handlers.get(event_type)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                await handler(data)
            else:
                handler(data)

    def subscribe(self, event_type: str, handler: cabc.Callable) -> None:
        self._handlers[event_type] = handler

    def get_events(self) -> list[dict]:
        return self._events.copy()
