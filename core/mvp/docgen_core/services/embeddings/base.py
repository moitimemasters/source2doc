import collections.abc as cabc
import typing as tp


class EmbeddingsService(tp.Protocol):
    async def embed_text(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: cabc.Sequence[str]) -> list[list[float]]: ...
