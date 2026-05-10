"""Tests for the incremental ingest pipeline (B2.4 / ТЗ ИНТ-04, ИНД-06).

The pipeline must:

* (a) chunk + embed every file when no prior hashes are recorded;
* (b) skip chunking and reuse existing Qdrant points for files whose
      sha256 matches the recorded baseline;
* (c) re-chunk + re-embed files whose content changed;
* (d) NOT carry deleted files forward into the new collection;
* (e) fall back to a full re-index when the previous collection is
      missing / unreachable.

We stub the Qdrant client (``FakeQdrantCopier``) so the test runs without
a Qdrant server and asserts on the points the pipeline tried to copy.
"""

from __future__ import annotations

import dataclasses as dc
import typing as tp

from source2doc.events.bus import EventBus
from source2doc.storage import FileSystem
from source2doc.storage.filesystem import detect_language as _detect_language  # noqa: F401

from docgen_core.pipeline import incremental as incremental_mod
from docgen_core.pipeline import ingest as ingest_pipeline


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingEventBus:
    """Captures emitted events without touching Redis."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, tp.Any]]] = []

    async def emit(self, event_type: str, data: dict[str, tp.Any]) -> None:
        self.events.append((event_type, data))


class _DictFileSystem(FileSystem):
    """In-memory filesystem keyed by relative path → file body."""

    def __init__(self, files: dict[str, str]) -> None:
        self._files = dict(files)

    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        return sorted(self._files.keys())

    async def read_file(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    async def file_exists(self, path: str) -> bool:
        return path in self._files


@dc.dataclass
class _FakePoint:
    """Minimal stand-in for a ``qdrant_client.models.Record``.

    Only the attributes ``copy_unchanged_file_points`` actually inspects
    are present (``id``, ``vector``, ``payload``).
    """

    id: int
    vector: list[float]
    payload: dict[str, tp.Any]


class _FakeQdrantCopier:
    """Implements :class:`incremental_mod.QdrantPointCopier` over an in-memory store.

    Tracks every scroll / upsert call so tests can assert on the carry-over
    behaviour. Toggle ``collection_present`` to simulate the "previous
    collection is missing" edge case.
    """

    def __init__(
        self,
        *,
        collection_present: bool = True,
        scroll_data: dict[str, list[_FakePoint]] | None = None,
        scroll_raises_for: tp.Iterable[str] = (),
    ) -> None:
        self.collection_present = collection_present
        self._scroll_data = scroll_data or {}
        self._scroll_raises_for = set(scroll_raises_for)
        self.scroll_calls: list[tuple[str, str]] = []
        self.upsert_calls: list[tuple[str, list[_FakePoint]]] = []
        self.collection_exists_calls: list[str] = []

    async def collection_exists(self, collection: str) -> bool:
        self.collection_exists_calls.append(collection)
        return self.collection_present

    async def scroll_points_for_file(self, collection: str, file_path: str) -> list[tp.Any]:
        self.scroll_calls.append((collection, file_path))
        if file_path in self._scroll_raises_for:
            raise RuntimeError(f"scroll exploded for {file_path}")
        return list(self._scroll_data.get(file_path, []))

    async def upsert_points(self, collection: str, points: list[tp.Any]) -> None:
        self.upsert_calls.append((collection, list(points)))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ingest_kwargs(
    fs: FileSystem,
    bus: EventBus,
    **overrides: tp.Any,
) -> dict[str, tp.Any]:
    return {
        "filesystem": fs,
        "chunk_size": 1024,
        "chunk_overlap": 0,
        "overlap_lines_divisor": 4,
        "event_bus": bus,
        **overrides,
    }


# ---------------------------------------------------------------------------
# (a) all-new files take the normal path
# ---------------------------------------------------------------------------


async def test_first_run_chunks_every_file_when_no_existing_hashes() -> None:
    fs = _DictFileSystem({"a.py": "print('a')\n", "b.py": "print('b')\n"})
    bus = _RecordingEventBus()
    copier = _FakeQdrantCopier()

    result = await ingest_pipeline.ingest_codebase(
        **_ingest_kwargs(
            fs,
            bus,
            existing_hashes={},
            previous_collection="docgen_old",
            new_collection="docgen_new",
            qdrant_copier=copier,
        )
    )

    assert {c.span.file_path for c in result.chunks} == {"a.py", "b.py"}
    assert result.carried_over_files == []
    # No incremental copy attempted: existing_hashes was empty, so the
    # copier's collection_exists / scroll / upsert are all untouched.
    assert copier.collection_exists_calls == []
    assert copier.scroll_calls == []
    assert copier.upsert_calls == []
    # Hashes are still recorded so the *next* run can take the fast path.
    assert {entry.file_path for entry in result.file_hashes} == {"a.py", "b.py"}
    assert all(entry.chunks_count > 0 for entry in result.file_hashes)


# ---------------------------------------------------------------------------
# (b) unchanged files reuse points
# ---------------------------------------------------------------------------


async def test_unchanged_files_skip_chunking_and_copy_points() -> None:
    body = "def stable():\n    return 1\n"
    fs = _DictFileSystem({"stable.py": body, "fresh.py": "fresh = True\n"})
    bus = _RecordingEventBus()

    sha = incremental_mod.compute_sha256(body)
    prior_points = [
        _FakePoint(id=42, vector=[0.1, 0.2, 0.3], payload={"file_path": "stable.py"}),
    ]
    copier = _FakeQdrantCopier(scroll_data={"stable.py": prior_points})

    result = await ingest_pipeline.ingest_codebase(
        **_ingest_kwargs(
            fs,
            bus,
            existing_hashes={"stable.py": sha},
            previous_collection="docgen_prev",
            new_collection="docgen_new",
            qdrant_copier=copier,
        )
    )

    # ``stable.py`` was not re-chunked.
    assert {c.span.file_path for c in result.chunks} == {"fresh.py"}
    # Copier was asked to carry the unchanged file's points across.
    assert copier.scroll_calls == [("docgen_prev", "stable.py")]
    assert len(copier.upsert_calls) == 1
    upsert_collection, upsert_points = copier.upsert_calls[0]
    assert upsert_collection == "docgen_new"
    # Original ids/vectors/payloads survive unchanged.
    assert [p.id for p in upsert_points] == [42]
    assert upsert_points[0].vector == [0.1, 0.2, 0.3]
    # Hash snapshot reflects both files (carried + freshly chunked).
    paths = {entry.file_path for entry in result.file_hashes}
    assert paths == {"stable.py", "fresh.py"}
    assert result.carried_over_files == ["stable.py"]
    # Per-file event explicitly flags the skip.
    skipped_events = [
        evt
        for evt in bus.events
        if evt[0] == "file.ingested" and evt[1].get("incremental") == "skipped_unchanged"
    ]
    assert len(skipped_events) == 1


# ---------------------------------------------------------------------------
# (c) changed files re-embed
# ---------------------------------------------------------------------------


async def test_changed_file_is_rechunked_with_new_hash() -> None:
    new_body = "def changed():\n    return 2\n"
    fs = _DictFileSystem({"changed.py": new_body})
    bus = _RecordingEventBus()

    stale_sha = incremental_mod.compute_sha256("old contents\n")
    copier = _FakeQdrantCopier()

    result = await ingest_pipeline.ingest_codebase(
        **_ingest_kwargs(
            fs,
            bus,
            existing_hashes={"changed.py": stale_sha},
            previous_collection="docgen_prev",
            new_collection="docgen_new",
            qdrant_copier=copier,
        )
    )

    # Changed file was re-chunked.
    assert {c.span.file_path for c in result.chunks} == {"changed.py"}
    # Nothing carried over.
    assert result.carried_over_files == []
    assert copier.scroll_calls == []
    assert copier.upsert_calls == []
    # The fresh hash matches the new body (not the stale one).
    new_sha = incremental_mod.compute_sha256(new_body)
    by_path = {entry.file_path: entry for entry in result.file_hashes}
    assert by_path["changed.py"].content_sha256 == new_sha
    assert by_path["changed.py"].content_sha256 != stale_sha


# ---------------------------------------------------------------------------
# (d) deleted files don't carry over
# ---------------------------------------------------------------------------


async def test_deleted_file_does_not_carry_to_new_collection() -> None:
    surviving_body = "still = True\n"
    fs = _DictFileSystem({"survivor.py": surviving_body})
    bus = _RecordingEventBus()

    survivor_sha = incremental_mod.compute_sha256(surviving_body)
    deleted_sha = incremental_mod.compute_sha256("orphan = True\n")
    copier = _FakeQdrantCopier(
        scroll_data={
            "survivor.py": [_FakePoint(id=1, vector=[0.0], payload={"file_path": "survivor.py"})],
            # The deleted file still has points in the prior collection,
            # but the pipeline must not ask for them.
            "deleted.py": [_FakePoint(id=99, vector=[0.0], payload={"file_path": "deleted.py"})],
        }
    )

    result = await ingest_pipeline.ingest_codebase(
        **_ingest_kwargs(
            fs,
            bus,
            existing_hashes={
                "survivor.py": survivor_sha,
                "deleted.py": deleted_sha,
            },
            previous_collection="docgen_prev",
            new_collection="docgen_new",
            qdrant_copier=copier,
        )
    )

    # No chunks emitted for the deleted file.
    assert {c.span.file_path for c in result.chunks} == set()
    # Carry-over targeted only the survivor.
    assert [path for _, path in copier.scroll_calls] == ["survivor.py"]
    # Hash snapshot does NOT contain the deleted file — its row will not
    # be inserted for this generation_id.
    assert {entry.file_path for entry in result.file_hashes} == {"survivor.py"}


# ---------------------------------------------------------------------------
# (e) prior collection missing → full re-index fallback
# ---------------------------------------------------------------------------


async def test_missing_previous_collection_falls_back_to_full_reindex() -> None:
    body = "x = 1\n"
    fs = _DictFileSystem({"a.py": body})
    bus = _RecordingEventBus()

    # Hash matches but the previous collection has been deleted/lost.
    sha = incremental_mod.compute_sha256(body)
    copier = _FakeQdrantCopier(collection_present=False)

    result = await ingest_pipeline.ingest_codebase(
        **_ingest_kwargs(
            fs,
            bus,
            existing_hashes={"a.py": sha},
            previous_collection="docgen_gone",
            new_collection="docgen_new",
            qdrant_copier=copier,
        )
    )

    # Defensive fallback: file gets re-chunked rather than left orphaned.
    assert {c.span.file_path for c in result.chunks} == {"a.py"}
    assert result.carried_over_files == []
    # We probed the collection but never tried to scroll / upsert.
    assert copier.collection_exists_calls == ["docgen_gone"]
    assert copier.scroll_calls == []
    assert copier.upsert_calls == []
    # Hash is still recorded for the next run.
    assert {entry.file_path for entry in result.file_hashes} == {"a.py"}


# ---------------------------------------------------------------------------
# Bonus coverage on the helpers themselves
# ---------------------------------------------------------------------------


def test_classify_file_buckets_correctly() -> None:
    existing = {"keep.py": "abc", "change.py": "old"}
    keep = incremental_mod.classify_file("keep.py", "abc", existing)
    change = incremental_mod.classify_file("change.py", "new", existing)
    new = incremental_mod.classify_file("new.py", "fresh", existing)

    assert keep.state == "unchanged"
    assert change.state == "changed"
    assert new.state == "new"


def test_compute_sha256_accepts_str_or_bytes() -> None:
    assert incremental_mod.compute_sha256("hello") == incremental_mod.compute_sha256(b"hello")


async def test_copy_unchanged_file_points_handles_per_file_failure() -> None:
    """One file's scroll exploding must not poison the rest."""

    copier = _FakeQdrantCopier(
        scroll_data={
            "ok.py": [_FakePoint(id=1, vector=[0.0], payload={"file_path": "ok.py"})],
        },
        scroll_raises_for=["broken.py"],
    )

    outcomes, fallbacks = await incremental_mod.copy_unchanged_file_points(
        file_paths=["ok.py", "broken.py"],
        previous_collection="docgen_prev",
        new_collection="docgen_new",
        copier=copier,
    )

    assert fallbacks == ["broken.py"]
    assert [o.file_path for o in outcomes] == ["ok.py"]
    assert outcomes[0].points_copied == 1


# ---------------------------------------------------------------------------
# Spec-required end-to-end coverage (B2.4 verification step)
#
# The TZ explicitly asks for two embedder-call-count tests: feeding the same
# content twice must call the embedder once total; feeding two distinct
# bodies must call it twice. We exercise the *combination* of ingest +
# index here so the assertion is on real embedder behaviour.
# ---------------------------------------------------------------------------


class _CountingEmbedder:
    """Records every embed_batch call so tests can assert call counts."""

    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.batch_calls: list[list[str]] = []

    async def embed_text(self, text: str) -> list[float]:
        return [0.0] * self.dim

    async def embed_batch(self, texts):  # type: ignore[no-untyped-def]
        # ``texts`` may be any sequence; coerce to list for stable assertions.
        captured = list(texts)
        self.batch_calls.append(captured)
        return [[0.0] * self.dim for _ in captured]


class _CapturingVectorStore:
    """Captures upsert / search / no-op delete + copy methods."""

    def __init__(self) -> None:
        self.upsert_calls: list[tuple[list[tp.Any], list[tp.Any]]] = []

    async def upsert(self, chunks, embeddings):  # type: ignore[no-untyped-def]
        self.upsert_calls.append((list(chunks), list(embeddings)))

    async def search(self, query_vector, limit=5):  # type: ignore[no-untyped-def]
        return []


async def _run_full_ingest_index(
    body_v1: str,
    body_v2: str,
    *,
    second_run_existing_hashes: dict[str, str] | None,
    embedder: _CountingEmbedder,
    vectorstore: _CapturingVectorStore,
) -> None:
    """Run ingest+index twice for ``a.py`` to exercise the spec scenarios.

    First run: no prior hashes → file gets chunked + embedded.
    Second run: ``second_run_existing_hashes`` controls whether the pipeline
    treats the file as unchanged (skip) or modified (re-embed).
    """

    from docgen_core.pipeline import index as index_pipeline

    # First run — fresh repo, no existing hashes.
    fs1 = _DictFileSystem({"a.py": body_v1})
    bus1 = _RecordingEventBus()
    res1 = await ingest_pipeline.ingest_codebase(
        **_ingest_kwargs(
            fs1,
            bus1,
            existing_hashes={},
            previous_collection=None,
            new_collection=None,
            qdrant_copier=None,
        )
    )
    if res1.chunks:
        await index_pipeline.index_chunks(
            res1.chunks,
            embedder,
            vectorstore,
            bus1,
            batch_size=64,
            concurrency=2,
        )

    # Second run — re-ingest with the snapshot from the first run.
    sha_v1 = incremental_mod.compute_sha256(body_v1)
    fs2 = _DictFileSystem({"a.py": body_v2})
    bus2 = _RecordingEventBus()
    # Precondition: the prior collection exists (so unchanged files can be
    # carried) and the copier returns the points the first run upserted.
    prior_points = [_FakePoint(id=99, vector=[0.0] * 4, payload={"file_path": "a.py"})]
    copier2 = _FakeQdrantCopier(scroll_data={"a.py": prior_points})
    res2 = await ingest_pipeline.ingest_codebase(
        **_ingest_kwargs(
            fs2,
            bus2,
            existing_hashes=second_run_existing_hashes
            if second_run_existing_hashes is not None
            else {"a.py": sha_v1},
            previous_collection="docgen_prev",
            new_collection="docgen_new",
            qdrant_copier=copier2,
        )
    )
    if res2.chunks:
        await index_pipeline.index_chunks(
            res2.chunks,
            embedder,
            vectorstore,
            bus2,
            batch_size=64,
            concurrency=2,
        )


async def test_unchanged_file_calls_embedder_only_on_first_run() -> None:
    """B2.4 — same content twice must hit the embedder exactly once total."""

    embedder = _CountingEmbedder()
    vectorstore = _CapturingVectorStore()

    body = "def stable():\n    return 1\n"
    await _run_full_ingest_index(
        body_v1=body,
        body_v2=body,
        second_run_existing_hashes=None,  # use sha(body_v1) → unchanged
        embedder=embedder,
        vectorstore=vectorstore,
    )

    # First run: 1 embed_batch call. Second run: zero — file was unchanged.
    assert len(embedder.batch_calls) == 1
    # Same shape on the vectorstore: only the first run upserted chunks.
    assert len(vectorstore.upsert_calls) == 1


async def test_modified_file_calls_embedder_on_both_runs() -> None:
    """B2.4 — different content on the second run must re-embed."""

    embedder = _CountingEmbedder()
    vectorstore = _CapturingVectorStore()

    await _run_full_ingest_index(
        body_v1="x = 1\n",
        body_v2="x = 2\n",  # different body → sha mismatch → re-embed
        second_run_existing_hashes=None,  # use sha(body_v1) for prior snapshot
        embedder=embedder,
        vectorstore=vectorstore,
    )

    # Both runs hit the embedder.
    assert len(embedder.batch_calls) == 2
    assert len(vectorstore.upsert_calls) == 2
