import typing as tp

import redis.asyncio as aioredis
import structlog

from source2doc.security.encryption import ConfigEncryption
from source2doc.storage import PostgresStorage
from source2doc.storage import codetour as codetour_storage_module

from worker.config import GatewayWorkerConfig


class CodetourWorkerEnv(tp.Protocol):
    config: GatewayWorkerConfig
    logger: structlog.stdlib.BoundLogger
    redis: aioredis.Redis | None
    storage: PostgresStorage | None
    codetour_storage: codetour_storage_module.CodetourStorage
    encryption: ConfigEncryption

    _initialized: bool
    _running: bool
