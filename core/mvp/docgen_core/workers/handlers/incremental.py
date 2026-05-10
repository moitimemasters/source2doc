"""Iterative-mode docgen orchestration handler.

Listens on ``iterative.index_completed`` (emitted by the index handler when
the gateway enqueued a task with ``iterative={…}``). The handler:

  1. Loads the base bundle's pages + index from Postgres.
  2. Classifies pages against ``changed_files`` / ``deleted_files`` into
     direct / transitive / dead / unchanged buckets via ``incremental_docs``.
  3. Creates a new ``documentation_bundles`` row with
     ``parent_generation_id`` pointing at the base bundle and
     ``generation_mode='incremental'``.
  4. Copies unchanged pages verbatim into the new bundle, copies dead
     pages with ``deprecated=True``.
  5. Builds an updated navigation (base navigation + orphan pages
     appended) and writes it to ``documentation_index`` for the new
     bundle so the wiki UI's nav resolves immediately.
  6. Synthesises page specs for orphan files via ``decide_orphan_actions``
     (heuristic, no LLM round-trip).
  7. For each affected (direct + transitive) page emits
     ``page.write_requested`` with an ``iterative_update`` payload
     containing the prior body + a diff stub. For each orphan spec
     emits ``page.write_requested`` in normal write mode.
  8. The existing write → diagram → review → evaluate → normalize →
     finalize pipeline takes over from there. ``ctx.expected_pages``
     counts only the writer-bound pages, so ``finalize._finalize_generation``
     fires once those are done; copied + dead pages are already in the
     bundle.
"""

from __future__ import annotations

import typing as tp
from uuid import UUID

from source2doc.git_context import GitContext
from source2doc.logging import get_logger
from source2doc.models import docs as doc_models
from source2doc.storage import FileSystem, LocalFileSystem, S3FileSystem

from docgen_core.pipeline import incremental_docs
from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod
from docgen_core.workers.handlers import ingest as ingest_handler


logger = get_logger(__name__)


async def _resolve_repo_path(filesystem: FileSystem):
    """Trigger extraction (if needed) and return the on-disk repo root.

    ``LocalFileSystem`` is cheap — ``base_path`` is set at construction.
    ``S3FileSystem`` extracts the tarball lazily on first read; we poke
    it via ``list_files`` to force the extract and then read the cached
    ``_extracted_path``. Returns ``None`` for filesystem types that
    don't expose a local path (currently no such type exists, but the
    fallback keeps the helper graceful).
    """
    if isinstance(filesystem, LocalFileSystem):
        return filesystem.base_path
    if isinstance(filesystem, S3FileSystem):
        # _ensure_extracted is the documented entry point used by every
        # read method; calling it directly avoids a fake list_files call.
        return await filesystem._ensure_extracted()
    base = getattr(filesystem, "base_path", None) or getattr(filesystem, "_extracted_path", None)
    return base


async def _compute_diff_from_commits(
    filesystem: FileSystem,
    from_commit: str,
    to_commit: str,
) -> tuple[list[str], list[str]]:
    """Resolve ``(changed, deleted)`` from a commit range using GitContext.

    The worker's ingest stage already extracted the repo tarball — for
    git-cloned repos that means ``.git/`` is on disk and we can run
    ``git diff`` directly. For archive uploads ``.git`` is absent and
    ``GitContext.is_available`` returns False; the helper logs a warning
    and returns ``([], [])`` so the orchestrator falls back to whatever
    the request supplied explicitly.
    """
    base_path = await _resolve_repo_path(filesystem)
    if base_path is None:
        logger.warning(
            "git_diff_filesystem_has_no_base_path",
            filesystem=type(filesystem).__name__,
        )
        return [], []
    git = GitContext(base_path)
    return await git.diff_changed_files(from_commit, to_commit)


def _resolve_project_name(repo_id: str | None, path: str | None) -> str:
    if repo_id:
        return f"repo-{repo_id[:8]}"
    if path:
        # mirror the basename-of-path convention used by the full-mode
        # subplan aggregator
        from pathlib import Path

        return Path(path).name or "documentation"
    return "documentation"


async def _build_diff_context(
    filesystem: FileSystem,
    page: dict,
    changed_files: set[str],
) -> list[dict[str, tp.Any]]:
    """Fetch the post-change full content for each file the page documents
    that's in ``changed_files``. We don't compute a unified diff here —
    the writer agent gets the page's prior body verbatim (so it knows the
    "before") and the file's current content, plus a hint about which
    parts are new. A real ``git diff`` would be richer, but it requires
    the caller to also supply the base commit's tree (``GitContext`` can
    do that, but only for git-cloned repos with a ``.git`` dir).
    """
    out: list[dict[str, tp.Any]] = []
    for path in sorted((page.get("source_files") or [])):
        if path not in changed_files:
            continue
        try:
            content = await filesystem.read_file(path)
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "iterative_diff_read_failed",
                path=path,
                error=str(exc),
            )
            content = ""
        # Truncate very large files so the writer prompt stays bounded.
        # 6kb is enough for most source files; the writer can re-read
        # specific ranges via the ``read_file`` tool if it needs more.
        snippet = content[:6000]
        suffix = "" if len(content) <= 6000 else "\n... [truncated; use read_file to fetch more]"
        out.append(
            {
                "path": path,
                "diff": snippet + suffix,
            }
        )
    return out


def _seed_navigation(
    base_navigation: dict[str, tp.Any] | None,
    orphan_specs: list[dict[str, tp.Any]],
) -> dict[str, str | dict]:
    """Stitch base navigation + orphan-page entries.

    Base navigation is preserved as-is (page_id → title). Orphan pages
    are appended to a top-level ``"_iterative_new"`` group so they show
    up in the wiki nav without disturbing the base section structure.
    """
    nav: dict[str, str | dict] = dict(base_navigation or {})
    if orphan_specs:
        nav["_iterative_new"] = {
            spec["page_id"]: spec["title"] for spec in orphan_specs
        }
    return nav


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    repo_id = data.get("repo_id")
    path = data.get("path")
    iterative_payload = data.get("iterative") or {}
    base_generation_id = iterative_payload.get("base_generation_id")
    changed_files: list[str] = list(iterative_payload.get("changed_files") or [])
    deleted_files: list[str] = list(iterative_payload.get("deleted_files") or [])
    name = data.get("name")
    description = data.get("description")

    if not base_generation_id:
        raise ValueError(
            "iterative mode requires base_generation_id in data['iterative']; got "
            f"{iterative_payload!r}"
        )

    # When the caller supplied a commit range and no explicit file list,
    # compute the diff via GitContext now (after ingest unpacked the
    # repo). The unpacked path is reachable through the same filesystem
    # the writer/critic later use for tools.
    from_commit = iterative_payload.get("from_commit")
    to_commit = iterative_payload.get("to_commit")
    if (not changed_files and not deleted_files) and from_commit and to_commit:
        diff_filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)
        diff_changed, diff_deleted = await _compute_diff_from_commits(
            diff_filesystem, from_commit, to_commit
        )
        changed_files = diff_changed
        deleted_files = diff_deleted
        logger.info(
            "iterative_diff_resolved_from_commits",
            from_commit=from_commit,
            to_commit=to_commit,
            changed=len(changed_files),
            deleted=len(deleted_files),
        )
        await env.event_bus.emit(
            "iterative.diff_computed",
            {
                "generation_id": generation_id,
                "from_commit": from_commit,
                "to_commit": to_commit,
                "changed_count": len(changed_files),
                "deleted_count": len(deleted_files),
            },
        )

    base_uuid = UUID(base_generation_id)
    new_uuid = UUID(generation_id)

    # 1. Load base pages + index. Pages must come from the dedicated
    # ``get_bundle_pages_full`` helper — the wiki-list shape doesn't carry
    # ``content`` / ``metadata`` / ``source_files`` which the rewriter
    # needs.
    base_pages = await env.storage.get_bundle_pages_full(base_uuid)
    if not base_pages:
        raise ValueError(
            f"base_generation_id {base_generation_id} has no pages — iterative mode "
            "requires a non-empty base bundle"
        )

    base_index = await env.storage.get_index(base_uuid)
    base_navigation = base_index.navigation if base_index else {}

    # 2. Classify pages.
    page_links = None
    try:
        page_links = await env.storage.get_page_links_for_generation(base_uuid)
    except Exception as exc:  # noqa: BLE001 — defensive (table may be empty)
        logger.warning("iterative_page_links_lookup_failed", error=str(exc))

    impact = incremental_docs.classify_pages(
        base_pages,
        changed_files,
        deleted_files,
        page_links=page_links,
    )

    # 3. Find orphan files + synthesise specs.
    orphan_files = incremental_docs.find_orphan_files(base_pages, changed_files)
    orphan_plan = incremental_docs.decide_orphan_actions(
        orphan_files,
        page_id_seed=generation_id,
    )

    await env.event_bus.emit(
        "iterative.classified",
        {
            "generation_id": generation_id,
            "base_generation_id": base_generation_id,
            "direct": len(impact.direct),
            "transitive": len(impact.transitive),
            "dead": len(impact.dead),
            "unchanged": len(impact.unchanged),
            "orphan_files": len(orphan_files),
            "orphan_specs": len(orphan_plan.page_specs),
        },
    )
    if orphan_files:
        await env.event_bus.emit(
            "iterative.new_files_unmapped",
            {
                "generation_id": generation_id,
                "files": orphan_files,
                "count": len(orphan_files),
                "specs": len(orphan_plan.page_specs),
            },
        )

    # 4. Create the new bundle. Project / repo / commit lookups mirror the
    # full-mode subplan aggregator so wiki + bundler downstream code sees
    # the same shape.
    project_name = _resolve_project_name(repo_id, path)
    bundle_id = await env.storage.create_bundle(
        new_uuid,
        project_name,
        name=name,
        description=description,
        repo_id=UUID(repo_id) if repo_id else None,
        parent_generation_id=base_uuid,
        generation_mode="incremental",
    )
    ctx.bundle_id = bundle_id

    if repo_id:
        try:
            repo_info = await env.storage.get_repository(UUID(repo_id))
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning(
                "iterative_repo_lookup_failed",
                repo_id=repo_id,
                error=str(exc),
            )
            repo_info = None
        ctx.commit_sha = repo_info.commit_sha if repo_info else None
        ctx.repository_id = repo_id
    else:
        ctx.commit_sha = None
        ctx.repository_id = None

    # 5. Copy unchanged pages verbatim, then dead pages as deprecated.
    if impact.unchanged:
        await env.storage.copy_pages_to_bundle(
            src_generation_id=base_uuid,
            dst_bundle_id=bundle_id,
            page_ids=impact.unchanged,
            new_commit_sha=ctx.commit_sha,
            mark_deprecated=False,
        )
        for page_id in impact.unchanged:
            await env.event_bus.emit(
                "iterative.page_copied",
                {
                    "generation_id": generation_id,
                    "page_id": page_id,
                    "deprecated": False,
                },
            )
    if impact.dead:
        await env.storage.copy_pages_to_bundle(
            src_generation_id=base_uuid,
            dst_bundle_id=bundle_id,
            page_ids=impact.dead,
            new_commit_sha=ctx.commit_sha,
            mark_deprecated=True,
        )
        for page_id in impact.dead:
            await env.event_bus.emit(
                "iterative.page_copied",
                {
                    "generation_id": generation_id,
                    "page_id": page_id,
                    "deprecated": True,
                },
            )

    # 6. Stitch navigation. Affected pages keep their existing nav slot;
    # orphan pages get appended under a synthetic group. The writer's
    # update-mode rewrite doesn't change page_id / title (and shouldn't —
    # it's an update, not a re-plan), so the base navigation entry stays
    # valid through the rewrite.
    navigation = _seed_navigation(base_navigation, orphan_plan.page_specs)
    index = doc_models.DocIndex.create(navigation=navigation)
    await env.storage.write_index(bundle_id, index)
    await env.event_bus.emit(
        "doc.index.created",
        {"generation_id": generation_id, "bundle_id": bundle_id},
    )

    # 7. Fan out writer rebuilds. Affected pages get an ``iterative_update``
    # payload (prior body + per-file diff stub). Orphan specs get the
    # vanilla writer treatment.
    affected = impact.all_affected()
    base_by_id = {p["page_id"]: p for p in base_pages}
    changed_set = set(changed_files)

    filesystem = ingest_handler._resolve_filesystem(env, repo_id, path)

    ctx.expected_pages = len(affected) + len(orphan_plan.page_specs)
    ctx.completed_pages.clear()
    ctx.failed_pages.clear()

    if ctx.expected_pages == 0:
        # Nothing to write — every page was either copied verbatim or
        # marked deprecated. Synthesise generation.completed directly.
        logger.info(
            "iterative_noop_no_writer_pages",
            generation_id=generation_id,
            unchanged=len(impact.unchanged),
            dead=len(impact.dead),
        )
        await env.event_bus.emit(
            "generation.completed",
            {
                "generation_id": generation_id,
                "bundle_id": bundle_id,
                "pages_count": len(impact.unchanged),
                "failed_pages_count": 0,
                "failed_pages": {},
            },
        )
        return

    for page_id in affected:
        page = base_by_id.get(page_id)
        if page is None:
            logger.warning(
                "iterative_affected_page_missing_in_base",
                page_id=page_id,
            )
            continue

        # Build the page_spec the writer expects. We rebuild it from the
        # persisted page rather than re-running the planner. Search
        # queries default to the page title — coarse but enough to seed
        # the writer's first RAG pass; the writer is also given the
        # prior body, which is the dominant signal.
        page_spec = {
            "page_id": page_id,
            "title": page["title"],
            "description": page.get("summary") or page["title"],
            "search_queries": [page["title"]],
            "source_files": list(page.get("source_files") or []),
            "iterative_origin": "rewrite",
        }
        ctx.page_specs[page_id] = page_spec
        ctx.page_attempts[page_id] = 1

        diff_context = await _build_diff_context(filesystem, page, changed_set)
        await env.event_bus.emit(
            "page.write_requested",
            {
                "generation_id": generation_id,
                "page_spec": page_spec,
                "repo_id": repo_id,
                "path": path,
                "attempt": 1,
                "iterative_update": {
                    "prior_body": page.get("content") or {},
                    "prior_summary": page.get("summary") or "",
                    "prior_metadata": page.get("metadata") or {},
                    "changed_files": diff_context,
                },
            },
        )

    for spec in orphan_plan.page_specs:
        page_id = spec["page_id"]
        ctx.page_specs[page_id] = spec
        ctx.page_attempts[page_id] = 1
        await env.event_bus.emit(
            "page.write_requested",
            {
                "generation_id": generation_id,
                "page_spec": spec,
                "repo_id": repo_id,
                "path": path,
                "attempt": 1,
                # No iterative_update — orphan pages are net-new content
                # and the writer should run in normal initial-mode.
            },
        )

    logger.info(
        "iterative_orchestrated",
        generation_id=generation_id,
        base_generation_id=base_generation_id,
        bundle_id=bundle_id,
        direct=len(impact.direct),
        transitive=len(impact.transitive),
        dead=len(impact.dead),
        unchanged=len(impact.unchanged),
        orphan_specs=len(orphan_plan.page_specs),
    )
