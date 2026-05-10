import typing as tp

import redis.asyncio as aioredis
import structlog

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage.prdoc import PRDocStorage

from worker.config import GatewayWorkerConfig


class PRDocWorkerEnv(tp.Protocol):
    config: GatewayWorkerConfig
    logger: structlog.stdlib.BoundLogger
    redis: aioredis.Redis | None
    storage: PostgresStorage | None
    prdoc_storage: PRDocStorage
    encryption: ConfigEncryption

    _initialized: bool
    _running: bool
