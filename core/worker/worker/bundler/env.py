import typing as tp

from source2doc.storage import S3Storage


if tp.TYPE_CHECKING:
    from worker.config import GatewayWorkerConfig


class BundlerWorkerEnv(tp.Protocol):
    s3_storage: S3Storage
    config: "GatewayWorkerConfig"
    logger: tp.Any
    _initialized: bool
    _running: bool
