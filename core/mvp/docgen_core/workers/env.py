import typing as tp

import jinja2

from source2doc import config, storage
from source2doc.events import bus

from docgen_core.services.embeddings.base import EmbeddingsService
from docgen_core.services.vectorstore.base import VectorStoreService


class DocGenEnv(tp.Protocol):
    config: config.AppConfig
    embeddings: EmbeddingsService
    vectorstore: VectorStoreService
    storage: storage.PostgresStorage
    event_bus: bus.EventBus
    s3_config: config.S3Config | None
    jinja_env: jinja2.Environment
    # Optional model-name -> pricing dict, plumbed from the worker config.
    # Handlers access this via getattr() so tests / older envs that don't
    # supply it still work — missing pricing => cost_usd recorded as null.
    pricing: tp.Mapping[str, tp.Any]
