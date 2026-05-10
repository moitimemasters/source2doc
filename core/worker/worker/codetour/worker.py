import structlog

from docgen_core.observability import setup_logfire
from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage import codetour as codetour_storage_module

from worker.codetour.env import CodetourWorkerEnv
from worker.codetour.processor import process_codetour_task
from worker.config import GatewayWorkerConfig
from worker.streams import base as stream_base
from worker.streams import consumer as consumer_mod


CODETOUR_STREAM = "tasks:codetour"
CODETOUR_CONSUMER_GROUP = "codetour-workers"


class CodetourWorker(stream_base.BaseStreamWorker, CodetourWorkerEnv):
    def __init__(self, config: GatewayWorkerConfig):
        super().__init__(
            redis_url=config.redis.url,
            stream_name=CODETOUR_STREAM,
            consumer_group=CODETOUR_CONSUMER_GROUP,
            worker_id=f"{config.worker_id}-codetour",
            max_retries=config.redis.max_retries,
            task_ttl=config.redis.stream_ttl_seconds,
            worker_concurrency=config.worker_concurrency,
        )
        self.config = config
        self.storage: PostgresStorage | None = None
        self.codetour_storage: codetour_storage_module.CodetourStorage | None = None
        self.encryption: ConfigEncryption | None = None
        self._init_logger = structlog.get_logger(__name__)

    async def async_init(self) -> None:
        await super().async_init()

        # setup_logfire silences pydantic_ai's "Logfire project URL: …" banner
        # even when logfire is disabled, so call it unconditionally.
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

        self.codetour_storage = codetour_storage_module.CodetourStorage(
            self.config.postgres.connection_string
        )
        await self.codetour_storage.connect()

        self.encryption = ConfigEncryption(self.config.encryption_key)

    async def _handle_message(self, message: consumer_mod.StreamMessage) -> None:
        task_info = message.data
        await process_codetour_task(self, task_info)

    async def _cleanup(self) -> None:
        if self.codetour_storage:
            await self.codetour_storage.close()
        if self.storage:
            await self.storage.close()
