import asyncio
import typing as tp

import redis.asyncio as aioredis
import structlog

from source2doc.logging import configure_logging

from worker.streams import consumer as consumer_mod


class BaseStreamWorker:
    def __init__(
        self,
        redis_url: str,
        stream_name: str,
        consumer_group: str,
        worker_id: str,
        max_retries: int = 3,
        task_ttl: int = 86400,
        worker_concurrency: int = 1,
    ):
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.worker_id = worker_id
        self.max_retries = max_retries
        self.task_ttl = task_ttl
        self.worker_concurrency = max(1, worker_concurrency)
        self.logger = structlog.get_logger(__name__)

        self._initialized = False
        self._running = False
        self.redis: aioredis.Redis | None = None
        # Semaphore caps parallel in-flight dispatches; only created when
        # concurrency > 1 so the legacy serial path stays unchanged.
        self._dispatch_sem: asyncio.Semaphore | None = (
            asyncio.Semaphore(self.worker_concurrency) if self.worker_concurrency > 1 else None
        )

    async def async_init(self) -> None:
        if self._initialized:
            return

        configure_logging("INFO")

        self.redis = await aioredis.from_url(
            self.redis_url,
            decode_responses=True,
        )

        await consumer_mod.ensure_consumer_group(
            self.redis,
            self.stream_name,
            self.consumer_group,
        )

        self._initialized = True

        self.logger.info(
            "worker_initialized",
            worker_id=self.worker_id,
            stream=self.stream_name,
            consumer_group=self.consumer_group,
        )

    async def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("Worker not initialized. Call async_init() first")

        self._running = True
        self.logger.info(
            "worker_started",
            worker_id=self.worker_id,
            stream=self.stream_name,
        )

        await self._run_consumer()

    async def stop(self) -> None:
        self.logger.info("stopping_worker", worker_id=self.worker_id)

        self._running = False

        await self._cleanup()

        if self.redis is not None:
            await self.redis.aclose()

        self.logger.info("worker_stopped", worker_id=self.worker_id)

    def is_running(self) -> bool:
        return self._running

    async def _run_consumer(self) -> None:
        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        await consumer_mod.run_consumer_loop(
            redis=self.redis,
            stream_name=self.stream_name,
            group_name=self.consumer_group,
            consumer_name=self.worker_id,
            handler=self._handle_message,
            running=self.is_running,
            max_retries=self.max_retries,
            task_ttl=self.task_ttl,
            semaphore=self._dispatch_sem,
            concurrency=self.worker_concurrency,
        )

    async def _handle_message(self, message: consumer_mod.StreamMessage) -> None:
        raise NotImplementedError("Subclasses must implement _handle_message")

    async def _cleanup(self) -> None:
        pass

    async def emit(
        self,
        stream_name: str,
        event_type: str,
        data: dict[str, tp.Any],
        ttl_seconds: int = 86400,
    ) -> str:
        if self.redis is None:
            raise RuntimeError("Redis not initialized")

        return await consumer_mod.emit_to_stream(
            self.redis,
            stream_name,
            event_type,
            data,
            ttl_seconds,
        )
