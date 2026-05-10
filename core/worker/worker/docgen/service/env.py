import typing as tp

import redis.asyncio as aioredis
import structlog

from source2doc import config, storage

from worker.config import GatewayWorkerConfig
from worker.encryption import ConfigEncryption


class DocGenServiceEnv(tp.Protocol):
    config: GatewayWorkerConfig
    redis: aioredis.Redis
    storage: storage.PostgresStorage
    encryption: ConfigEncryption
    logger: structlog.stdlib.BoundLogger
    worker_id: str

    _initialized: bool
    _running: bool
