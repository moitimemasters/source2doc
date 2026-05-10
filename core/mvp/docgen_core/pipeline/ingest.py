import collections
import collections.abc as cabc
import dataclasses as dc
import hashlib

from source2doc import get_logger
from source2doc.events.bus import EventBus
from source2doc.models.chunks import CodeChunk, FileSpan
from source2doc.storage import FileSystem
from source2doc.storage.filesystem import detect_language
from source2doc.storage.postgres import FileHashEntry

from docgen_core.pipeline import incremental as incremental_mod


logger = get_logger(__name__)


class EmptyCorpusError(RuntimeError):
    """Raised when ingest finds no documentable files in the repository.

    Carries a structured ``reason`` so the worker can emit a precise
    ``task.failed`` event instead of silently producing empty pages.
    """

    def __init__(self, reason: str, files_count: int = 0, chunks_count: int = 0) -> None:
        self.reason = reason
        self.files_count = files_count
        self.chunks_count = chunks_count
        super().__init__(f"empty_corpus: {reason} (files={files_count}, chunks={chunks_count})")


@dc.dataclass
class IngestResult:
    chunks: list[CodeChunk]
    dominant_language: str
    language_counts: dict[str, int]
    # B2.4 / ТЗ ИНТ-04, ИНД-06 — outputs of the incremental hashing flow.
    # ``file_hashes`` is the full snapshot for the new generation (one
    # entry per file, including both newly chunked files and unchanged
    # ones whose points were carried over from the previous collection).
    # ``carried_over_files`` lists paths whose Qdrant points were copied
    # (chunks for these files are NOT in ``chunks`` — they don't need
    # re-embedding). Both default to empty so non-incremental callers
    # (local path, no repo_id) keep working unchanged.
    file_hashes: list[FileHashEntry] = dc.field(default_factory=list)
    carried_over_files: list[str] = dc.field(default_factory=list)


async def create_chunks(
    file_path: str,
    filesystem: FileSystem,
    chunk_size: int,
    chunk_overlap: int,
    overlap_lines_divisor: int,
    event_bus: EventBus,
    *,
    preloaded_content: str | None = None,
) -> list[CodeChunk]:
    """Split a file into ``CodeChunk`` records.

    ``preloaded_content`` lets the incremental path read the file once
    (to compute its hash) and pass the body straight through, avoiding a
    second filesystem call. Legacy callers that still pass only a
    filesystem keep working — we read on demand.
    """

    if preloaded_content is None:
        try:
            content = await filesystem.read_file(file_path)
        except (UnicodeDecodeError, OSError) as e:
            logger.info("skip_unreadable_file", file=file_path, error=str(e))
            return []
    else:
        content = preloaded_content

    lines = content.splitlines()
    language = detect_language(file_path)

    chunks = []
    start_line = 1

    while start_line <= len(lines):
        end_line = start_line
        chunk_content = ""

        while end_line <= len(lines) and len(chunk_content) < chunk_size:
            chunk_content += lines[end_line - 1] + "\n"
            end_line += 1

        chunk_id = hashlib.sha256(f"{file_path}:{start_line}-{end_line}".encode()).hexdigest()[:16]

        chunk = CodeChunk(
            chunk_id=chunk_id,
            span=FileSpan(
                file_path=file_path,
                start_line=start_line,
                end_line=end_line - 1,
            ),
            content=chunk_content.strip(),
            language=language,
        )
        chunks.append(chunk)

        await event_bus.emit(
            "chunk.created",
            {
                "file": file_path,
                "chunk_id": chunk_id,
                "lines": f"{start_line}-{end_line - 1}",
                "language": language,
            },
        )

        overlap_lines = max(1, chunk_overlap // overlap_lines_divisor)
        next_start = end_line - overlap_lines
        start_line = max(next_start, start_line + 1)

        if end_line > len(lines):
            break

    return chunks


async def _read_for_hash(filesystem: FileSystem, file_path: str) -> str | None:
    """Return the file's text, or ``None`` if the read failed.

    We log + swallow the same errors ``create_chunks`` would so a broken
    file doesn't poison the whole ingest. Returning ``None`` causes the
    caller to treat the file as unreadable (no hash, no chunks, no
    carry-over).
    """

    try:
        return await filesystem.read_file(file_path)
    except (UnicodeDecodeError, OSError) as exc:
        logger.info("skip_unreadable_file", file=file_path, error=str(exc))
        return None


async def ingest_codebase(
    filesystem: FileSystem,
    chunk_size: int,
    chunk_overlap: int,
    overlap_lines_divisor: int,
    event_bus: EventBus,
    *,
    existing_hashes: cabc.Mapping[str, str] | None = None,
    previous_collection: str | None = None,
    new_collection: str | None = None,
    qdrant_copier: incremental_mod.QdrantPointCopier | None = None,
) -> IngestResult:
    """Walk the repo, chunk new/changed files, carry the rest of the points across.

    The incremental path activates when ``existing_hashes`` is non-empty
    *and* a copier + both collection names are supplied. Missing any of
    those falls through to the legacy "chunk every file" behaviour. We
    still compute hashes on every file so the *next* run gets to skip
    work even when this one couldn't.

    For unchanged files the point copy is attempted via ``qdrant_copier``;
    on any failure (collection missing, scroll error, etc.) the affected
    files fall back to the normal chunk + embed path. Correctness over
    efficiency — a partial Qdrant outage must not lose chunks.

    Files that disappeared between runs are simply absent from the new
    snapshot's ``file_hashes`` and from the new collection. The previous
    collection still holds the orphan points, but the new one won't.
    """

    files = await filesystem.list_files(".")
    total_files = len(files)

    logger.info("ingest_started", files_count=total_files)
    await event_bus.emit("ingest.started", {"files_count": total_files})

    if total_files == 0:
        raise EmptyCorpusError("no_supported_files_found", files_count=0, chunks_count=0)

    existing = dict(existing_hashes or {})
    can_incremental = (
        bool(existing)
        and qdrant_copier is not None
        and previous_collection is not None
        and new_collection is not None
    )

    # Phase 1: classify each file by hash. Files with read failures are
    # dropped entirely — no hash, no chunks, no carry-over.
    decisions: list[incremental_mod.IncrementalDecision] = []
    file_contents: dict[str, str] = {}
    for file_path in files:
        content = await _read_for_hash(filesystem, file_path)
        if content is None:
            continue
        file_contents[file_path] = content
        sha = incremental_mod.compute_sha256(content)
        decisions.append(
            incremental_mod.classify_file(file_path, sha, existing if can_incremental else {})
        )

    unchanged_paths = [d.file_path for d in decisions if d.state == "unchanged"]
    chunk_paths: set[str] = {d.file_path for d in decisions if d.state != "unchanged"}

    # Phase 2: try to carry unchanged files' points across collections.
    # Anything that fails the copy gets demoted to a normal re-chunk so
    # the new collection still ends up with its embeddings.
    copy_outcomes: list[incremental_mod.CopyOutcome] = []
    if can_incremental and unchanged_paths:
        copy_outcomes, fallback_paths = await incremental_mod.copy_unchanged_file_points(
            file_paths=unchanged_paths,
            previous_collection=previous_collection,  # type: ignore[arg-type]
            new_collection=new_collection,  # type: ignore[arg-type]
            copier=qdrant_copier,  # type: ignore[arg-type]
        )
        if fallback_paths:
            fallback_set = set(fallback_paths)
            unchanged_paths = [p for p in unchanged_paths if p not in fallback_set]
            chunk_paths.update(fallback_set)
    elif unchanged_paths and not can_incremental:
        # Hashes matched but we don't have a way to carry points across
        # (no copier / no collection names). Demote to "changed" so they
        # get re-chunked along with everything else; correctness wins.
        chunk_paths.update(unchanged_paths)
        unchanged_paths = []

    unchanged_set = set(unchanged_paths)

    # Phase 3: chunk the new/changed files. We re-walk decisions in the
    # original order so ``language_counts`` and per-file events stay
    # deterministic w.r.t. the filesystem listing.
    language_counts: collections.Counter[str] = collections.Counter()
    all_chunks: list[CodeChunk] = []
    file_hashes: list[FileHashEntry] = []

    for idx, decision in enumerate(decisions, 1):
        file_path = decision.file_path

        if file_path in unchanged_set:
            logger.debug(
                "ingest.skipped_unchanged",
                file=file_path,
                sha256=decision.current_sha256[:12],
            )
            carried_chunks = next(
                (o.points_copied for o in copy_outcomes if o.file_path == file_path),
                0,
            )
            file_hashes.append(
                FileHashEntry(
                    file_path=file_path,
                    content_sha256=decision.current_sha256,
                    chunks_count=carried_chunks,
                )
            )
            await event_bus.emit(
                "file.ingested",
                {
                    "file": file_path,
                    "chunks_count": carried_chunks,
                    "index": idx,
                    "total": total_files,
                    "incremental": "skipped_unchanged",
                },
            )
            continue

        if file_path not in chunk_paths:
            # Read failed earlier — already logged, skip silently.
            continue

        logger.info(
            "processing_file",
            file=file_path,
            progress=f"{idx}/{total_files}",
        )
        chunks = await create_chunks(
            file_path,
            filesystem,
            chunk_size,
            chunk_overlap,
            overlap_lines_divisor,
            event_bus,
            preloaded_content=file_contents.get(file_path),
        )
        all_chunks.extend(chunks)
        if chunks:
            language_counts[chunks[0].language] += len(chunks)

        file_hashes.append(
            FileHashEntry(
                file_path=file_path,
                content_sha256=decision.current_sha256,
                chunks_count=len(chunks),
            )
        )

        await event_bus.emit(
            "file.ingested",
            {
                "file": file_path,
                "chunks_count": len(chunks),
                "index": idx,
                "total": total_files,
            },
        )

    # An ingest run must produce *something* downstream: either fresh
    # chunks for changed files or carried-over points for unchanged
    # ones. Both empty => same legacy "all_files_unreadable_or_empty"
    # error so downstream task.failed payloads stay stable.
    if not all_chunks and not unchanged_paths:
        raise EmptyCorpusError(
            "all_files_unreadable_or_empty",
            files_count=total_files,
            chunks_count=0,
        )

    if language_counts:
        dominant_language = language_counts.most_common(1)[0][0]
    else:
        # All files were carried over without re-chunking — derive the
        # dominant language from filename heuristics so downstream
        # planner/writer agents still get a sane signal.
        derived: collections.Counter[str] = collections.Counter()
        for path in unchanged_paths:
            derived[detect_language(path)] += 1
        dominant_language = derived.most_common(1)[0][0] if derived else "text"

    logger.info(
        "ingest_completed",
        total_chunks=len(all_chunks),
        dominant_language=dominant_language,
        languages=dict(language_counts),
        carried_over_files=len(unchanged_paths),
        carried_over_points=sum(o.points_copied for o in copy_outcomes),
    )

    return IngestResult(
        chunks=all_chunks,
        dominant_language=dominant_language,
        language_counts=dict(language_counts),
        file_hashes=file_hashes,
        carried_over_files=unchanged_paths,
    )
