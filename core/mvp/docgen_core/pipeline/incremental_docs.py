"""Page-level classification + planning for iterative-mode docgen.

The full-mode pipeline replans, rewrites and re-reviews every page on each
generation. Iterative mode short-circuits that: given the prior bundle's
pages and a list of files that changed (or were deleted) since, we bucket
the pages into ``direct`` / ``transitive`` / ``dead`` / ``unchanged`` and
the writer only re-runs against the first three. Files that aren't covered
by any existing page (``orphan_files``) get a small set of fresh page
specs the writer will author from scratch.

The functions here are storage-agnostic: ``classify_pages`` works on plain
dicts (whatever ``PostgresStorage.get_bundle_pages_full`` returns) and
``decide_orphan_actions`` reuses the same dict shape. Tests inject these
without touching Postgres.
"""

from __future__ import annotations

import collections
import dataclasses as dc
import hashlib
import os
import typing as tp


@dc.dataclass(frozen=True)
class PageImpact:
    """Bucketing of base-bundle pages against a ``changed/deleted_files``
    set.

    ``direct`` pages must be re-written by the writer in update-mode (their
    source code moved). ``transitive`` pages have no direct overlap but
    link to a ``direct`` page via ``page_links`` — their text mentions
    something that just changed, so they get re-written too (1-hop only,
    callers can disable by passing ``page_links=None``). ``dead`` pages
    are copied with ``deprecated=True`` so the wiki still renders the
    history but the nav greys them. ``unchanged`` pages are byte-identical
    copies of the base.
    """

    direct: list[str]
    transitive: list[str]
    dead: list[str]
    unchanged: list[str]

    def all_affected(self) -> list[str]:
        """``direct + transitive`` — pages that need writer re-runs."""
        return list(self.direct) + list(self.transitive)


@dc.dataclass(frozen=True)
class OrphanPlan:
    """New page specs synthesised for files that aren't covered by any
    existing page.

    ``page_specs`` is shaped to match what the planner agent emits so the
    write handler can consume them without a special path. Each spec has a
    stable ``page_id`` (hash of the grouping key + a short random nonce
    derived from the orphan file list) so re-running the same iterative
    job is idempotent.
    """

    page_specs: list[dict[str, tp.Any]]
    skipped_files: list[str]


def _normalise(files: tp.Iterable[str]) -> set[str]:
    """Path normalisation — strip leading ``./`` so a writer-supplied
    ``./src/foo.py`` matches a caller-supplied ``src/foo.py``. Empty
    strings are dropped.
    """
    out: set[str] = set()
    for f in files:
        if not f:
            continue
        out.add(f[2:] if f.startswith("./") else f)
    return out


def classify_pages(
    base_pages: tp.Sequence[dict[str, tp.Any]],
    changed_files: tp.Iterable[str],
    deleted_files: tp.Iterable[str] = (),
    *,
    page_links: tp.Iterable[tuple[str, str, str, int]] | None = None,
    transitive_min_weight: int = 1,
) -> PageImpact:
    """Bucket ``base_pages`` against a ``(changed, deleted)`` file pair.

    Each base page is expected to expose ``page_id`` (str) and
    ``source_files`` (list[str]). Pages with empty ``source_files`` are
    treated conservatively as ``direct`` whenever *anything* changed —
    we don't know what they cover, so the safer call is to refresh them.

    A page is ``dead`` only when every one of its ``source_files`` is in
    ``deleted_files`` (and ``source_files`` is non-empty). A page is
    ``direct`` when it has at least one ``source_files`` entry overlapping
    ``changed_files`` (excluding deleted files — those make it ``dead``
    instead). The remainder become ``unchanged``, then ``page_links`` are
    walked one hop to promote any ``unchanged`` page into ``transitive``
    if it links to a ``direct`` (or transitive) page with weight
    ≥ ``transitive_min_weight``.

    ``page_links`` is the four-tuple shape returned by
    ``PostgresStorage.get_page_links_for_generation``:
    ``(from_page_id, to_page_id, kind, weight)``. Pass ``None`` to skip
    the transitive expansion entirely.
    """

    changed = _normalise(changed_files)
    deleted = _normalise(deleted_files)

    direct: list[str] = []
    dead: list[str] = []
    unchanged_set: set[str] = set()

    for page in base_pages:
        page_id = page["page_id"]
        sources = _normalise(page.get("source_files") or [])

        if not sources:
            # Unknown coverage. If there's nothing to compare against,
            # treat as direct so the page gets refreshed; otherwise a
            # silently-empty source_files would freeze the page forever
            # across iterative runs.
            if changed or deleted:
                direct.append(page_id)
            else:
                unchanged_set.add(page_id)
            continue

        if sources and sources <= deleted:
            dead.append(page_id)
            continue

        live_sources = sources - deleted
        if live_sources & changed:
            direct.append(page_id)
            continue

        unchanged_set.add(page_id)

    direct_set = set(direct)
    transitive_set: set[str] = set()
    if page_links is not None and direct_set:
        # 1-hop expansion: any unchanged page that links to a direct page
        # with weight >= threshold gets promoted. We do NOT recurse —
        # transitive(transitive) is rare in practice and rebuilding the
        # full reachable set risks dragging the entire bundle into the
        # rewrite path. Single hop catches "page A documents fn() which
        # is referenced from page B" without runaway expansion.
        for from_id, to_id, _kind, weight in page_links:
            if weight < transitive_min_weight:
                continue
            if to_id in direct_set and from_id in unchanged_set:
                transitive_set.add(from_id)

    unchanged = sorted(unchanged_set - transitive_set)
    transitive = sorted(transitive_set)

    return PageImpact(
        direct=sorted(direct),
        transitive=transitive,
        dead=sorted(dead),
        unchanged=unchanged,
    )


def find_orphan_files(
    base_pages: tp.Sequence[dict[str, tp.Any]],
    changed_files: tp.Iterable[str],
) -> list[str]:
    """``changed_files`` minus every file referenced by any base page.

    These are files the iterative caller introduced (or that existed but
    weren't covered by the prior plan) — the writer will need brand-new
    page specs to document them. Returns a sorted list for deterministic
    handling.
    """
    changed = _normalise(changed_files)
    covered: set[str] = set()
    for page in base_pages:
        covered |= _normalise(page.get("source_files") or [])
    return sorted(changed - covered)


def decide_orphan_actions(
    orphan_files: tp.Sequence[str],
    *,
    max_files_per_page: int = 5,
    page_id_seed: str = "",
) -> OrphanPlan:
    """Group orphan files into fresh page specs, one spec per directory.

    Heuristic: files that share a parent directory document a coherent
    sub-component, so a single page covers them. If a directory has more
    than ``max_files_per_page`` orphans the directory is split into
    multiple specs (``foo/__1``, ``foo/__2`` …) so writer prompts stay
    bounded. Files at the repo root land in a single ``__root__`` page.

    The mini-planner is intentionally heuristic, not LLM-driven — adding
    an LLM round-trip on every iterative run defeats the cost-saving
    point of the mode. Callers that want richer plans can post-process
    ``page_specs`` (e.g. drop spam, merge tiny dirs) before handing them
    to the writer.

    Returns an ``OrphanPlan`` whose ``page_specs`` carry the same fields
    the writer's ``page.write_requested`` handler expects: ``page_id``,
    ``title``, ``description``, ``search_queries`` (used by the writer's
    initial RAG pass).
    """

    if not orphan_files:
        return OrphanPlan(page_specs=[], skipped_files=[])

    # Bucket orphans by parent directory ("." for repo-root files).
    by_dir: dict[str, list[str]] = collections.defaultdict(list)
    for path in orphan_files:
        parent = os.path.dirname(path) or "."
        by_dir[parent].append(path)

    specs: list[dict[str, tp.Any]] = []
    skipped: list[str] = []

    for parent, files in sorted(by_dir.items()):
        files_sorted = sorted(files)
        # Long directories get sliced — keeps writer prompt under control
        # and avoids a single page summarising 50 unrelated files.
        for chunk_idx in range(0, len(files_sorted), max_files_per_page):
            chunk = files_sorted[chunk_idx : chunk_idx + max_files_per_page]
            page_id = _orphan_page_id(parent, chunk_idx, page_id_seed, chunk)
            title = _orphan_title(parent, chunk_idx, len(files_sorted), max_files_per_page)
            description = (
                f"Documents the source files added or surfaced in '{parent}/' that the prior "
                f"bundle didn't cover. Files: {', '.join(chunk)}."
            )
            # ``search_queries`` seeds the writer's initial RAG pass. We
            # use the file basenames as queries — they tend to align with
            # class/function names better than directory paths do.
            queries = [os.path.basename(p) for p in chunk]
            specs.append(
                {
                    "page_id": page_id,
                    "title": title,
                    "description": description,
                    "search_queries": queries[:5],
                    # Stamp the source files explicitly so the writer +
                    # finalize pipeline can treat the orphan plan as
                    # already-source-files-tagged (touched_files will
                    # also pick them up if the agent reads them).
                    "source_files": chunk,
                    "iterative_origin": "orphan_planner",
                }
            )

    return OrphanPlan(page_specs=specs, skipped_files=skipped)


def _orphan_page_id(parent: str, chunk_idx: int, seed: str, files: tp.Sequence[str]) -> str:
    """Stable, short page_id derived from the directory + chunk index +
    seed. The seed lets callers (e.g. the iterative handler) make the id
    unique to the current generation when needed; default empty seed
    means "same orphan files in the same dir → same id" which is the
    desired idempotency property for replays.
    """
    body = f"{seed}|{parent}|{chunk_idx}|{'|'.join(files)}"
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:10]
    if parent == ".":
        slug = "root"
    else:
        slug = parent.replace("/", "-").replace("\\", "-").strip("-") or "dir"
    return f"orphan-{slug}-{digest}"


def _orphan_title(parent: str, chunk_idx: int, total_files: int, chunk_size: int) -> str:
    if parent == ".":
        base = "Repository root files"
    else:
        base = f"{parent} (new files)"
    if total_files <= chunk_size:
        return base
    # Multi-chunk directory — disambiguate.
    return f"{base} (part {chunk_idx // chunk_size + 1})"
