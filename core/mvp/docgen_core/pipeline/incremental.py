"""Per-file content hashing for incremental re-indexing (B2.4).

The ingest pipeline calls into this module when a ``repository_id`` is in
play. For each file we compute ``sha256(file_bytes)`` and compare against
the most recent recorded hash. Unchanged files have their existing Qdrant
points carried forward into the new collection (same id / vector /
payload) so search behaves identically without re-running the embedder.

The helpers here are intentionally storage-agnostic: a tiny ``QdrantPointCopier``
protocol abstracts the Qdrant ``scroll`` + ``upsert`` round-trip so tests
can inject a fake without spinning up a server. Failures during point copy
fall back to a full re-index for the affected files (logged, never crash).
"""

from __future__ import annotations

import collections.abc as cabc
import dataclasses as dc
import hashlib
import typing as tp

from source2doc.logging import get_logger


logger = get_logger(__name__)


# Cap memory: never scroll more than this many points per file in one batch.
# Files are usually a handful of chunks; 256 leaves slack without being
# pathological for huge generated/lockfile-style sources.
SCROLL_PAGE_SIZE = 256

# When copying points for many unchanged files, batch the file list so we
# don't hold thousands of pending scroll futures at once. The TZ asks for
# 100 explicitly.
COPY_FILE_BATCH = 100


def compute_sha256(content: str | bytes) -> str:
    """Hex-encoded SHA-256 of the file's contents.

    Accepts either ``bytes`` or ``str``; ``str`` is encoded as UTF-8 to
    match what ``LocalFileSystem.read_file`` already returns from disk.
    """

    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


@dc.dataclass(frozen=True)
class IncrementalDecision:
    """Outcome of comparing a file's current hash against the prior snapshot.

    ``unchanged`` => we will skip chunking + embedding and copy the prior
    Qdrant points across. ``changed`` => the file was previously indexed
    but its content moved on; we re-chunk + re-embed. ``new`` => first
    time we've seen this path for the repo.
    """

    file_path: str
    current_sha256: str
    state: tp.Literal["unchanged", "changed", "new"]


def classify_file(
    file_path: str,
    current_sha256: str,
    existing_hashes: cabc.Mapping[str, str],
) -> IncrementalDecision:
    """Bucket a file as ``unchanged`` / ``changed`` / ``new``.

    ``existing_hashes`` is the ``file_path → sha256`` map returned by
    ``PostgresStorage.get_file_hashes``. Empty map (first-ever ingest)
    short-circuits everything to ``new``.
    """

    prior = existing_hashes.get(file_path)
    if prior is None:
        state: tp.Literal["unchanged", "changed", "new"] = "new"
    elif prior == current_sha256:
        state = "unchanged"
    else:
        state = "changed"
    return IncrementalDecision(
        file_path=file_path,
        current_sha256=current_sha256,
        state=state,
    )


class QdrantPointCopier(tp.Protocol):
    """Thin port over the Qdrant client for copying points across collections.

    The real implementation lives in :class:`AsyncQdrantPointCopier`; tests
    inject a fake. Both sides only need ``scroll_points_for_file`` (read
    from the previous-generation collection) and ``upsert_points`` (write
    into the current-generation collection with identical ids/vectors/payloads).
    """

    async def scroll_points_for_file(
        self,
        collection: str,
        file_path: str,
    ) -> list[tp.Any]: ...

    async def upsert_points(
        self,
        collection: str,
        points: list[tp.Any],
    ) -> None: ...

    async def collection_exists(self, collection: str) -> bool: ...

    async def count_points(self, collection: str) -> int: ...


@dc.dataclass
class CopyOutcome:
    """Result of attempting to carry one file's points across collections.

    ``points_copied`` is what actually landed in the new collection;
    ``fell_back`` flags files we gave up on (collection missing, scroll
    raised, etc.) — the caller treats those as ``changed`` so they get
    chunked + re-embedded along the normal path.
    """

    file_path: str
    points_copied: int
    fell_back: bool


async def copy_unchanged_file_points(
    *,
    file_paths: cabc.Sequence[str],
    previous_collection: str,
    new_collection: str,
    copier: QdrantPointCopier,
) -> tuple[list[CopyOutcome], list[str]]:
    """Carry Qdrant points for unchanged files across collections.

    Returns ``(outcomes, fallback_paths)``. ``fallback_paths`` is the
    subset of ``file_paths`` whose copy failed — the caller must re-chunk
    + re-embed those files instead. If the previous collection is
    completely unreachable / missing, every file falls back (logged once).

    Memory cap: processes ``file_paths`` in batches of ``COPY_FILE_BATCH``
    (currently 100) so a 10k-file repo doesn't queue 10k concurrent
    scroll calls. Inside a batch each file is handled sequentially —
    Qdrant scroll already returns large pages so per-file concurrency
    buys little.
    """

    if not file_paths:
        return [], []

    try:
        prev_exists = await copier.collection_exists(previous_collection)
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "incremental.previous_collection_check_failed",
            collection=previous_collection,
            error=str(exc),
        )
        return [], list(file_paths)

    if not prev_exists:
        logger.warning(
            "incremental.previous_collection_missing",
            collection=previous_collection,
            files=len(file_paths),
        )
        return [], list(file_paths)

    # Guard against carrying from a prior collection that was created but
    # never populated (e.g. the prior generation died mid-index due to disk
    # pressure). Otherwise every file scroll returns 0 points, each is logged
    # as a "no-op carry", and the new collection silently ends up empty —
    # then writers/critics report "not found in codebase" for everything.
    try:
        prev_point_count = await copier.count_points(previous_collection)
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "incremental.previous_collection_count_failed",
            collection=previous_collection,
            error=str(exc),
        )
        prev_point_count = -1

    if prev_point_count == 0:
        logger.warning(
            "incremental.previous_collection_empty",
            collection=previous_collection,
            files=len(file_paths),
        )
        return [], list(file_paths)

    outcomes: list[CopyOutcome] = []
    fallback_paths: list[str] = []

    for batch_start in range(0, len(file_paths), COPY_FILE_BATCH):
        batch = file_paths[batch_start : batch_start + COPY_FILE_BATCH]
        for file_path in batch:
            try:
                points = await copier.scroll_points_for_file(
                    previous_collection,
                    file_path,
                )
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning(
                    "incremental.scroll_failed",
                    file=file_path,
                    collection=previous_collection,
                    error=str(exc),
                )
                fallback_paths.append(file_path)
                continue

            if not points:
                # Nothing to carry — the file was previously empty / un-chunked.
                # Treat as a clean no-op, not a fallback.
                outcomes.append(CopyOutcome(file_path=file_path, points_copied=0, fell_back=False))
                continue

            try:
                await copier.upsert_points(new_collection, points)
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning(
                    "incremental.upsert_failed",
                    file=file_path,
                    collection=new_collection,
                    error=str(exc),
                )
                fallback_paths.append(file_path)
                continue

            outcomes.append(
                CopyOutcome(
                    file_path=file_path,
                    points_copied=len(points),
                    fell_back=False,
                )
            )

    logger.info(
        "incremental.points_copied",
        previous_collection=previous_collection,
        new_collection=new_collection,
        files_carried=len([o for o in outcomes if not o.fell_back]),
        files_fell_back=len(fallback_paths),
        total_points=sum(o.points_copied for o in outcomes),
    )
    return outcomes, fallback_paths


class AsyncQdrantPointCopier:
    """Real :class:`QdrantPointCopier` over ``qdrant_client.AsyncQdrantClient``.

    Owns the client lifecycle so callers don't have to thread ``url`` /
    ``api_key`` through every helper. Closed via ``aclose()`` once the
    incremental phase is done.
    """

    def __init__(self, url: str, api_key: str | None = None) -> None:
        # Lazy import: tests inject a fake copier and never need the real client.
        import qdrant_client

        self._client = qdrant_client.AsyncQdrantClient(url=url, api_key=api_key)

    async def collection_exists(self, collection: str) -> bool:
        try:
            collections = await self._client.get_collections()
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "incremental.get_collections_failed",
                error=str(exc),
            )
            return False
        return any(c.name == collection for c in collections.collections)

    async def count_points(self, collection: str) -> int:
        info = await self._client.get_collection(collection_name=collection)
        # ``points_count`` is the authoritative tally; ``vectors_count`` and
        # ``indexed_vectors_count`` may lag during background indexing.
        return int(info.points_count or 0)

    async def scroll_points_for_file(
        self,
        collection: str,
        file_path: str,
    ) -> list[tp.Any]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        flt = Filter(
            must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))],
        )
        all_points: list[tp.Any] = []
        offset: tp.Any = None
        while True:
            points, next_offset = await self._client.scroll(
                collection_name=collection,
                scroll_filter=flt,
                limit=SCROLL_PAGE_SIZE,
                with_payload=True,
                with_vectors=True,
                offset=offset,
            )
            all_points.extend(points)
            if next_offset is None:
                break
            offset = next_offset
        return all_points

    async def upsert_points(self, collection: str, points: list[tp.Any]) -> None:
        from qdrant_client.models import PointStruct

        # Re-pack into PointStructs so the new collection sees an
        # honest-to-goodness payload write rather than a Record echo.
        # ids, vectors, payloads are preserved verbatim.
        prepared: list[PointStruct] = []
        for p in points:
            prepared.append(
                PointStruct(
                    id=p.id,
                    vector=p.vector,
                    payload=p.payload or {},
                )
            )
        await self._client.upsert(collection_name=collection, points=prepared)

    async def aclose(self) -> None:
        try:
            await self._client.close()
        except Exception:  # noqa: BLE001 — defensive
            pass
