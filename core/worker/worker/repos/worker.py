from source2doc.storage import PostgresStorage, S3Storage

from worker.config import GatewayWorkerConfig
from worker.repos.env import RepoWorkerEnv
from worker.repos.processor import process_repository_upload
from worker.streams import base as stream_base
from worker.streams import consumer as consumer_mod


REPOS_STREAM = "tasks:repos"
REPOS_CONSUMER_GROUP = "repos-workers"


class RepoWorker(stream_base.BaseStreamWorker, RepoWorkerEnv):
    def __init__(self, config: GatewayWorkerConfig):
        super().__init__(
            redis_url=config.redis.url,
            stream_name=REPOS_STREAM,
            consumer_group=REPOS_CONSUMER_GROUP,
            worker_id=f"{config.worker_id}-repos",
            max_retries=config.redis.max_retries,
            task_ttl=config.redis.stream_ttl_seconds,
            worker_concurrency=config.worker_concurrency,
        )
        self.config = config
        self.s3_storage = S3Storage(config.s3)
        self.pg_storage = PostgresStorage(config.postgres.connection_string)

    async def async_init(self) -> None:
        await super().async_init()
        await self.pg_storage.connect()

    async def _cleanup(self) -> None:
        await self.pg_storage.close()

    async def _handle_message(self, message: consumer_mod.StreamMessage) -> None:
        task_info = message.data
        await process_repository_upload(self, task_info)
