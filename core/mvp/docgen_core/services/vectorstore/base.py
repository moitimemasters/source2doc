import collections.abc as cabc
import typing as tp

from source2doc.models.chunks import CodeChunk


class VectorStoreService(tp.Protocol):
    async def upsert(
        self,
        chunks: cabc.Sequence[CodeChunk],
        embeddings: cabc.Sequence[list[float]],
    ) -> None: ...

    async def search(
        self,
        query_vector: cabc.Sequence[float],
        limit: int = 5,
    ) -> list[CodeChunk]: ...

    async def ensure_collection(self) -> None: ...
