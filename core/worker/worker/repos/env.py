import typing as tp

import redis.asyncio as aioredis
import structlog

from source2doc.storage import PostgresStorage, S3Storage

from worker.config import GatewayWorkerConfig


class RepoWorkerEnv(tp.Protocol):
    config: GatewayWorkerConfig
    logger: structlog.stdlib.BoundLogger
    redis: aioredis.Redis | None
    s3_storage: S3Storage
    pg_storage: PostgresStorage

    _initialized: bool
    _running: bool
