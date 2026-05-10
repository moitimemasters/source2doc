import asyncio
import dataclasses as dc

from source2doc import get_logger
from source2doc.events.bus import EventBus
from source2doc.models.chunks import CodeChunk

from docgen_core.services.embeddings.base import EmbeddingsService
from docgen_core.services.vectorstore.base import VectorStoreService


logger = get_logger(__name__)


@dc.dataclass
class BatchResult:
    batch_index: int
    embeddings: list[list[float]]


async def _process_batch(
    embeddings_service: EmbeddingsService,
    texts: list[str],
    batch_index: int,
) -> BatchResult:
    """Embed a single batch with bounded retries on transient HTTP errors.

    Yandex eliza intermittently returns timeouts on long requests; the
    indexer used to abort the whole task on the first failure. Three
    retries with linear backoff lets the indexer ride out a slow upstream
    without taking the entire generation down.
    """
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            embeddings = await embeddings_service.embed_batch(texts)
            return BatchResult(batch_index=batch_index, embeddings=embeddings)
        except Exception as exc:  # noqa: BLE001 — retry any provider error once
            last_exc = exc
            logger.warning(
                "embedding_batch_failed",
                batch_index=batch_index,
                attempt=attempt,
                error=str(exc)[:200],
                error_type=type(exc).__name__,
            )
            if attempt < 3:
                await asyncio.sleep(attempt * 2.0)
    assert last_exc is not None
    raise last_exc


async def index_chunks(
    chunks: list[CodeChunk],
    embeddings_service: EmbeddingsService,
    vectorstore: VectorStoreService,
    event_bus: EventBus,
    batch_size: int,
    concurrency: int = 4,
) -> None:
    """Embed and upsert chunks for changed/new files.

    Incremental ingest (B2.4) already filtered ``chunks`` to the changed/new
    set before this runs and carried the unchanged files' Qdrant points
    across collections directly, so this function stays oblivious to
    incremental concerns. An empty ``chunks`` list is a legitimate outcome
    when nothing has changed since the last run — we short-circuit with an
    info log instead of treating it as an error.
    """
    if not chunks:
        logger.info("index_skipped_no_changed_chunks")
        await event_bus.emit("index.started", {"chunks_count": 0})
        return

    logger.info(
        "index_started",
        chunks_count=len(chunks),
        batch_size=batch_size,
        concurrency=concurrency,
    )
    await event_bus.emit("index.started", {"chunks_count": len(chunks)})

    # Token-aware adaptive batching. Many embedding endpoints (Yandex,
    # OpenAI text-embedding-3-small) cap batch input at 32768 tokens. With
    # a fixed batch_size=100 a fastapi-sized repo silently produces a
    # batch summing to >32k tokens and the API 400s. We approximate token
    # count as chars/4 and pack each batch up to ``MAX_BATCH_CHARS``
    # (30000 tokens × 4 = 120k chars), capped at ``batch_size`` items so
    # tiny chunks still ship in reasonable groups. Oversized single
    # chunks (one >MAX_BATCH_CHARS) are truncated up front so they
    # never overflow on their own.
    # Lowered batch caps: not just to fit the 32k token API limit but also
    # to keep the per-request wall-clock under the httpx read timeout.
    # Yandex eliza-served embeddings spend ~15-30s on a 60k-char batch.
    MAX_BATCH_CHARS = 60_000  # ≈ 15k tokens
    MAX_SINGLE_CHARS = 16_000  # ≈ 4k tokens — fits in any single embedding

    batches: list[tuple[int, list[str]]] = []
    cursor = 0
    while cursor < len(chunks):
        batch_start = cursor
        batch_chars = 0
        texts: list[str] = []
        while cursor < len(chunks) and len(texts) < batch_size:
            content = chunks[cursor].content
            if len(content) > MAX_SINGLE_CHARS:
                content = content[:MAX_SINGLE_CHARS]
                logger.warning(
                    "chunk_truncated_for_embedding",
                    chunk_id=chunks[cursor].chunk_id,
                    original_chars=len(chunks[cursor].content),
                    truncated_to=MAX_SINGLE_CHARS,
                )
            if texts and batch_chars + len(content) > MAX_BATCH_CHARS:
                # Adding this text would exceed the per-batch cap. Flush
                # the current batch and start fresh.
                break
            texts.append(content)
            batch_chars += len(content)
            cursor += 1
        batches.append((batch_start, texts))

    logger.info("embeddings_batches_prepared", batches_count=len(batches))

    all_embeddings: list[list[float]] = [[] for _ in range(len(chunks))]
    processed = 0

    semaphore = asyncio.Semaphore(concurrency)

    async def process_with_semaphore(
        batch_index: int,
        texts: list[str],
    ) -> BatchResult:
        async with semaphore:
            return await _process_batch(embeddings_service, texts, batch_index)

    tasks = [process_with_semaphore(batch_idx, texts) for batch_idx, texts in batches]

    for coro in asyncio.as_completed(tasks):
        result = await coro

        start_idx = result.batch_index
        for j, emb in enumerate(result.embeddings):
            if start_idx + j < len(all_embeddings):
                all_embeddings[start_idx + j] = emb

        processed += len(result.embeddings)
        logger.info("embeddings_batch_processed", processed=processed, total=len(chunks))
        await event_bus.emit("embeddings.batch", {"processed": processed, "total": len(chunks)})

    logger.info("embeddings_generated", count=len(all_embeddings))
    await event_bus.emit("embeddings.generated", {"count": len(all_embeddings)})

    logger.info("storing_in_vectordb", chunks_count=len(chunks))
    await vectorstore.upsert(chunks, all_embeddings)
    logger.info("vectordb_storage_completed")
