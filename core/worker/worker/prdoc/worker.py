"""Stream consumer for the ``tasks:prdoc`` group."""

from __future__ import annotations

import structlog

from docgen_core.observability import setup_logfire
from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage.prdoc import PRDocStorage

from worker.config import GatewayWorkerConfig
from worker.prdoc.env import PRDocWorkerEnv  # noqa: F401 — re-exported for tests
from worker.prdoc.processor import process_prdoc_task
from worker.streams import base as stream_base
from worker.streams import consumer as consumer_mod


PRDOC_STREAM = "tasks:prdoc"
PRDOC_CONSUMER_GROUP = "prdoc-workers"


class PRDocWorker(stream_base.BaseStreamWorker):
    def __init__(self, config: GatewayWorkerConfig) -> None:
        super().__init__(
            redis_url=config.redis.url,
            stream_name=PRDOC_STREAM,
            consumer_group=PRDOC_CONSUMER_GROUP,
            worker_id=f"{config.worker_id}-prdoc",
            max_retries=config.redis.max_retries,
            task_ttl=config.redis.stream_ttl_seconds,
        )
        self.config = config
        self.storage: PostgresStorage | None = None
        self.prdoc_storage: PRDocStorage | None = None
        self.encryption: ConfigEncryption | None = None
        self._init_logger = structlog.get_logger(__name__)

    async def async_init(self) -> None:
        await super().async_init()

        if self.config.logfire.enabled:
            try:
                setup_logfire(self.config.logfire)
            except Exception as exc:  # noqa: BLE001
                self._init_logger.error(
                    "logfire_setup_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        self.storage = PostgresStorage(self.config.postgres.connection_string)
        await self.storage.connect()

        self.prdoc_storage = PRDocStorage(self.config.postgres.connection_string)
        await self.prdoc_storage.connect()

        self.encryption = ConfigEncryption(self.config.encryption_key)

    async def _handle_message(self, message: consumer_mod.StreamMessage) -> None:
        await process_prdoc_task(self, message.data)

    async def _cleanup(self) -> None:
        if self.prdoc_storage is not None:
            await self.prdoc_storage.close()
        if self.storage is not None:
            await self.storage.close()
