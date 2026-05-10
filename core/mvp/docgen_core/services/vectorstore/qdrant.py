import collections.abc as cabc
from contextlib import suppress

import qdrant_client
import qdrant_client.models as qmodels

from source2doc.config import QdrantConfig
from source2doc.models.chunks import CodeChunk, FileSpan
from source2doc.resilience import qdrant_retry


class QdrantVectorStore:
    def __init__(self, config: QdrantConfig, vector_size: int = 1536) -> None:
        self.config = config
        self.resilience = config.resilience
        self.vector_size = vector_size
        self.client = qdrant_client.AsyncQdrantClient(
            url=config.url,
            api_key=config.api_key,
        )

    @qdrant_retry()
    async def _get_collections(self):
        return await self.client.get_collections()

    @qdrant_retry()
    async def _create_collection(self) -> None:
        await self.client.create_collection(
            collection_name=self.config.collection,
            vectors_config=qmodels.VectorParams(
                size=self.vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        )

    @qdrant_retry()
    async def _upsert_batch(self, batch: list[qmodels.PointStruct]) -> None:
        await self.client.upsert(
            collection_name=self.config.collection,
            points=batch,
        )

    @qdrant_retry()
    async def _query_points(self, query_vector: list[float], limit: int):
        return await self.client.query_points(
            collection_name=self.config.collection,
            query=query_vector,
            limit=limit,
        )

    @qdrant_retry()
    async def _delete_collection(self) -> None:
        await self.client.delete_collection(collection_name=self.config.collection)

    async def ensure_collection(self) -> None:
        collections = await self._get_collections()
        exists = any(c.name == self.config.collection for c in collections.collections)

        if not exists:
            await self._create_collection()

    async def upsert(
        self,
        chunks: cabc.Sequence[CodeChunk],
        embeddings: cabc.Sequence[list[float]],
        batch_size: int = 256,
    ) -> None:
        await self.ensure_collection()

        points = [
            qmodels.PointStruct(
                id=hash(chunk.chunk_id) & 0x7FFFFFFFFFFFFFFF,
                vector=embedding,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "file_path": chunk.span.file_path,
                    "start_line": chunk.span.start_line,
                    "end_line": chunk.span.end_line,
                    "content": chunk.content,
                    "language": chunk.language,
                },
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]

        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            await self._upsert_batch(batch)

    async def search(
        self,
        query_vector: cabc.Sequence[float],
        limit: int = 5,
    ) -> list[CodeChunk]:
        results = await self._query_points(list(query_vector), limit)

        chunks = []
        for point in results.points:
            payload = point.payload
            if payload is None:
                continue
            chunk = CodeChunk(
                chunk_id=payload["chunk_id"],
                span=FileSpan(
                    file_path=payload["file_path"],
                    start_line=payload["start_line"],
                    end_line=payload["end_line"],
                ),
                content=payload["content"],
                language=payload["language"],
            )
            chunks.append(chunk)

        return chunks

    async def clear(self) -> None:
        with suppress(Exception):
            await self._delete_collection()

        await self._create_collection()
