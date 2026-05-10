import typing as tp

import httpx
from openai import AsyncOpenAI

from source2doc.config import EmbeddingsConfig

from docgen_core.services.yandex_transport import YandexHTTPTransport


class OpenAIEmbeddingsEnv(tp.Protocol):
    embeddings_config: EmbeddingsConfig


def create_client(config: EmbeddingsConfig) -> AsyncOpenAI:
    transport = YandexHTTPTransport(verify=False)
    http_client = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
    )
    return AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        http_client=http_client,
    )


async def embed_text(client: AsyncOpenAI, model: str, text: str) -> list[float]:
    response = await client.embeddings.create(
        model=model,
        input=text,
    )
    return response.data[0].embedding


async def embed_batch(client: AsyncOpenAI, model: str, texts: list[str]) -> list[list[float]]:
    response = await client.embeddings.create(
        model=model,
        input=texts,
    )
    return [item.embedding for item in response.data]


class OpenAIEmbeddings:
    def __init__(self, config: EmbeddingsConfig) -> None:
        self.config = config
        self._client = create_client(config)

    async def embed_text(self, text: str) -> list[float]:
        return await embed_text(self._client, self.config.model, text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await embed_batch(self._client, self.config.model, texts)
