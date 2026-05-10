import typing as tp

import redis.asyncio as aioredis
import structlog


class StreamWorkerEnv(tp.Protocol):
    redis: aioredis.Redis
    logger: structlog.stdlib.BoundLogger
    worker_id: str
    consumer_group: str
    _initialized: bool
    _running: bool
