from source2doc.storage import S3Storage

from worker.bundler.env import BundlerWorkerEnv
from worker.bundler.processor import process_bundle_export
from worker.config import GatewayWorkerConfig
from worker.streams import base as stream_base
from worker.streams import consumer as consumer_mod


BUNDLER_STREAM = "tasks:bundler"
BUNDLER_CONSUMER_GROUP = "bundler-workers"


class BundlerWorker(stream_base.BaseStreamWorker, BundlerWorkerEnv):
    def __init__(self, config: GatewayWorkerConfig):
        super().__init__(
            redis_url=config.redis.url,
            stream_name=BUNDLER_STREAM,
            consumer_group=BUNDLER_CONSUMER_GROUP,
            worker_id=f"{config.worker_id}-bundler",
            max_retries=config.redis.max_retries,
            task_ttl=config.redis.stream_ttl_seconds,
            worker_concurrency=config.worker_concurrency,
        )
        self.config = config
        self.s3_storage = S3Storage(config.s3)

    async def _handle_message(self, message: consumer_mod.StreamMessage) -> None:
        task_info = message.data
        await process_bundle_export(self, task_info)
