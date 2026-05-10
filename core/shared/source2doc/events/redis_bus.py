import asyncio
import collections.abc as cabc
import json
from uuid import UUID

import redis.asyncio as aioredis

from source2doc.config import RedisConfig
from source2doc.events.bus import annotate_event
from source2doc.logging import get_logger
from source2doc.pipelines.types import Pipeline
from source2doc.resilience.external import redis_retry


class RedisEventBus:
    def __init__(
        self,
        config: RedisConfig,
        generation_id: UUID,
        pipeline: Pipeline | None = None,
    ) -> None:
        self.config = config
        self.generation_id = generation_id
        self.stream_name = f"{config.stream_prefix}:{generation_id}"
        self.client: aioredis.Redis | None = None
        self._consumer_task: asyncio.Task | None = None
        self._handlers: dict[str, cabc.Callable] = {}
        self._running = False
        self.pipeline = pipeline
        self.logger = get_logger(__name__)

    async def connect(self) -> None:
        self.client = await aioredis.from_url(
            self.config.url,
            decode_responses=True,
        )
        await self._ensure_consumer_group()

    async def _ensure_consumer_group(self) -> None:
        try:
            await self.client.xgroup_create(
                name=self.stream_name,
                groupname=self.config.consumer_group,
                id="0",
                mkstream=True,
            )
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def emit(self, event_type: str, data: dict) -> None:
        # Hard-stop: in-flight handlers that completed AFTER the user
        # clicked stop are normally past the dispatcher's cancel-check.
        # They keep emitting follow-up events (page.failed, page.written,
        # ...) for ~tens of seconds, which the user perceives as
        # "execution resumed". Suppressing emits here makes the stop
        # take effect immediately on the timeline — the in-flight LLM
        # work still finishes (we don't abort httpx mid-call) but its
        # output never reaches the events stream, so no successor
        # handler ever fires. Audit events from the gateway (task.stopped,
        # task.resumed) bypass this bus and xadd directly, so they are
        # unaffected.
        if await self._is_cancelled():
            self.logger.info(
                "event_emit_suppressed_cancelled",
                event_type=event_type,
                generation_id=str(self.generation_id),
            )
            return

        payload = {"generation_id": str(self.generation_id), **data}
        payload = annotate_event(self.pipeline, event_type, payload, self.logger)
        await self._xadd_with_retry(event_type, payload)
        await self.client.expire(self.stream_name, self.config.stream_ttl_seconds)
        self.logger.info("event_emitted", event_type=event_type)

    async def _is_cancelled(self) -> bool:
        if self.client is None:
            return False
        try:
            flag = await self.client.hget(
                f"state:docgen:{self.generation_id}", "cancelled"
            )
        except Exception as exc:  # noqa: BLE001
            # Never block emits on a Redis hiccup — log and continue. The
            # dispatcher's cancel-check is a second line of defence.
            self.logger.warning("cancel_flag_check_failed", error=str(exc)[:200])
            return False
        return flag == "true"

    @redis_retry()
    async def _xadd_with_retry(self, event_type: str, payload: dict) -> None:
        await self.client.xadd(
            name=self.stream_name,
            fields={
                "type": event_type,
                "data": json.dumps(payload),
            },
        )

    @redis_retry()
    async def _xack_with_retry(self, message_id: str) -> None:
        await self.client.xack(
            self.stream_name,
            self.config.consumer_group,
            message_id,
        )

    def subscribe(self, event_type: str, handler: cabc.Callable) -> None:
        self._handlers[event_type] = handler
        if not self._running:
            self._running = True
            self._consumer_task = asyncio.create_task(self._consume_loop())

    async def _consume_loop(self) -> None:
        await self._recover_pending()

        while self._running:
            try:
                messages = await self.client.xreadgroup(
                    groupname=self.config.consumer_group,
                    consumername=self.config.consumer_name,
                    streams={self.stream_name: ">"},
                    count=1,
                    block=self.config.block_timeout_ms,
                )

                if not messages:
                    continue

                for _stream_name, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        await self._process_message(message_id, fields)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("consumer_loop_error", error=str(e))
                await asyncio.sleep(1)

    async def _recover_pending(self) -> None:
        pending = await self.client.xpending_range(
            name=self.stream_name,
            groupname=self.config.consumer_group,
            min="-",
            max="+",
            count=100,
        )

        for msg in pending:
            if msg["time_since_delivered"] > self.config.max_idle_time_ms:
                claimed = await self.client.xclaim(
                    name=self.stream_name,
                    groupname=self.config.consumer_group,
                    consumername=self.config.consumer_name,
                    min_idle_time=self.config.max_idle_time_ms,
                    message_ids=[msg["message_id"]],
                )

                for message_id, fields in claimed:
                    await self._process_message(message_id, fields)

    async def _process_message(self, message_id: str, fields: dict) -> None:
        event_type = fields.get("type")
        data = json.loads(fields.get("data", "{}"))

        handler = self._handlers.get(event_type)
        if handler:
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    await result

                await self._xack_with_retry(message_id)
            except Exception as e:
                self.logger.exception(
                    "handler_error",
                    event_type=event_type,
                    message_id=message_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )

                await self._emit_handler_error(event_type, data, e)

    async def _emit_handler_error(
        self,
        event_type: str | None,
        data: dict,
        exc: Exception,
    ) -> None:
        try:
            await self._xadd_with_retry(
                "handler.error",
                {
                    "failed_event_type": event_type,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "generation_id": data.get("generation_id"),
                },
            )
        except Exception as emit_err:
            self.logger.error(
                "failed_to_emit_handler_error",
                error=str(emit_err),
            )

    async def close(self) -> None:
        self._running = False

        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await asyncio.wait_for(self._consumer_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception as e:
                self.logger.error("consumer_task_close_error", error=str(e))

        if self.client:
            try:
                await self.client.aclose()
            except Exception as e:
                self.logger.error("redis_close_error", error=str(e))

    def get_events(self) -> list[dict]:
        return asyncio.run(self._get_events_async())

    async def _get_events_async(self) -> list[dict]:
        messages = await self.client.xrange(self.stream_name, "-", "+")

        events = []
        for message_id, fields in messages:
            events.append(
                {
                    "id": message_id,
                    "type": fields.get("type"),
                    "data": json.loads(fields.get("data", "{}")),
                }
            )

        return events
