import collections.abc as cabc

import httpx
from openai import AsyncOpenAI

from source2doc.config import EmbeddingsConfig

from docgen_core.services.yandex_transport import YandexHTTPTransport


class OpenAIEmbeddings:
    def __init__(self, config: EmbeddingsConfig) -> None:
        self.config = config
        transport = YandexHTTPTransport(verify=False)
        # Read timeout bumped 60→180s — Yandex eliza-served qwen embeddings
        # routinely take >60s on a 60k-char batch. Tighter timeouts surface
        # as task-killing 'Request timed out' on the index phase.
        http_client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=10.0),
        )
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            http_client=http_client,
        )

    async def embed_text(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model=self.config.model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: cabc.Sequence[str]) -> list[list[float]]:
        response = await self.client.embeddings.create(
            model=self.config.model,
            input=list(texts),
        )
        return [item.embedding for item in response.data]
