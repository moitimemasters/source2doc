import re
import typing as tp
from uuid import UUID

from source2doc import DocPage
from source2doc.formatter.mdx import blocks as mdx_blocks
from source2doc.logging import get_logger
from source2doc.storage.postgres import PageLinkEntry

from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod


logger = get_logger(__name__)


# Per-page hard cap on outbound edges to keep pathological pages from
# saturating ``page_links``. A typical page yields well under 50 edges;
# the cap is a defensive ceiling, not an expected limit.
_MAX_EDGES_PER_PAGE = 200


# ---------------------------------------------------------------------------
# Cross-page symbol extraction (B6.2 / ТЗ ДОК-08)
# ---------------------------------------------------------------------------
#
# We harvest a small dictionary of "symbols" per persisted page so the wiki
# can render inline mentions as hyperlinks to the symbol's home page.
# The heuristic is intentionally simple — no AST, no language detection.

# CamelCase types: ``DocPage``, ``ReactMarkdown``, ``HTTPError``.
_CAMEL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*[a-z][A-Za-z0-9]*$")
# snake_case_with_parens: ``record_page_symbols(...)`` / ``foo_bar()``.
_FUNC_CALL_RE = re.compile(r"^([a-z_][a-z0-9_]*)\s*\((?:[^)]*)\)$")
# Backticked identifier inside body Markdown: ``` `Identifier` ```.
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
# Common English / Cyrillic stopwords we never want to link.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "it",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "but",
        "by",
        "with",
        "as",
        "if",
        "this",
        "that",
        "these",
        "those",
        "be",
        "are",
        "was",
        "were",
        "from",
        "at",
        "into",
        "и",
        "в",
        "на",
        "с",
        "по",
        "для",
        "это",
    }
)


def _classify_identifier(token: str) -> str | None:
    """Return ``'class'`` / ``'function'`` if ``token`` looks like a code symbol,
    or ``None`` if we should skip it.
    """
    token = token.strip()
    if not token or len(token) < 3 or len(token) > 80:
        return None
    if token.lower() in _STOPWORDS:
        return None
    m = _FUNC_CALL_RE.match(token)
    if m:
        name = m.group(1)
        if name in _STOPWORDS or len(name) < 3:
            return None
        return "function"
    if _CAMEL_CASE_RE.match(token):
        return "class"
    return None


def _block_attr(block: tp.Any, key: str) -> tp.Any:
    """Read ``key`` from a Pydantic block model OR a plain dict."""
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def _iter_block_text(blocks: tp.Iterable[tp.Any]) -> tp.Iterator[str]:
    """Yield every textual fragment in a block tree."""
    for block in blocks:
        block_type = _block_attr(block, "type")

        if block_type in ("paragraph", "callout", "quote", "heading"):
            text = _block_attr(block, "text")
            if isinstance(text, str):
                yield text
        elif block_type == "list":
            for item in _block_attr(block, "items") or []:
                t = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
                if isinstance(t, str):
                    yield t
        elif block_type == "table":
            for header in _block_attr(block, "headers") or []:
                if isinstance(header, str):
                    yield header
            for row in _block_attr(block, "rows") or []:
                for cell in row or []:
                    if isinstance(cell, str):
                        yield cell
        elif block_type == "cut":
            inner = _block_attr(block, "blocks") or []
            yield from _iter_block_text(inner)


def extract_page_symbols(page: DocPage) -> list[tuple[str, str]]:
    """Return ``(symbol, kind)`` pairs for the cross-page link index.

    Sources:
    * The page title and h1/h2 markdown headings → ``page_title`` (alias).
    * Backtick-wrapped identifiers in body text that look like
      ``CamelCase`` (→ ``class``) or ``snake_func()`` (→ ``function``).
    """
    symbols: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(symbol: str, kind: str) -> None:
        symbol = (symbol or "").strip()
        if not symbol:
            return
        key = (symbol.lower(), kind)
        if key in seen:
            return
        seen.add(key)
        symbols.append((symbol, kind))

    if page.title:
        _add(page.title, "page_title")

    for block in page.blocks:
        block_type = getattr(block, "type", None)
        if block_type == "heading":
            level = getattr(block, "level", 0)
            text = getattr(block, "text", "")
            if level in (1, 2) and isinstance(text, str):
                _add(text, "page_title")

    for text in _iter_block_text(page.blocks):
        for match in _BACKTICK_RE.finditer(text):
            token = match.group(1)
            kind = _classify_identifier(token)
            if kind is None:
                continue
            symbol = token.split("(")[0].strip()
            _add(symbol, kind)

    return symbols


def _render_page_markdown(page: DocPage) -> str:
    """Render a ``DocPage`` to GitHub-flavored Markdown.

    Mirrors ``app.routes.docs.service._render_page_markdown`` so the
    snapshot we persist matches the body the gateway re-renders for the
    "Download Markdown" button on the latest page. We keep the two
    copies in sync via a comment rather than a shared helper because
    pulling a gateway-internal renderer into the worker layer would
    invert the dependency direction.
    """
    lines: list[str] = [f"# {page.title}", ""]
    if page.summary:
        lines.append(page.summary)
        lines.append("")

    for block in page.blocks:
        lines.extend(mdx_blocks.format_block(block))
        lines.append("")

    if page.related:
        lines.append("## Related Pages")
        lines.append("")
        for related_id in page.related:
            lines.append(f"- [{related_id}](./{related_id}.md)")
        lines.append("")

    return "\n".join(lines)


async def _record_page_version(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    generation_id: str,
    page_id: str,
    page: DocPage,
) -> None:
    """Best-effort wrapper around ``storage.record_page_version`` (B11.2).

    Failure here must never break finalize — losing one history entry is
    a degraded UX, not a data-loss event (the canonical row in
    ``documentation_pages`` is still written by ``write_page`` above).
    """
    storage = env.storage
    if not hasattr(storage, "record_page_version"):
        return
    try:
        # Include title/summary in the snapshot body even though
        # ``documentation_pages.content`` doesn't carry them — historical
        # reads need them to render a self-contained view (a writer agent
        # may rename a page between runs).
        body = {
            "title": page.title,
            "summary": page.summary,
            "blocks": [block.model_dump() for block in page.blocks],
            "related": page.related,
        }
        metadata = page.metadata.model_dump()
        body_markdown = _render_page_markdown(page)
        repository_uuid = UUID(ctx.repository_id) if ctx.repository_id else None
        await storage.record_page_version(
            page_id=page_id,
            generation_id=UUID(generation_id),
            repository_id=repository_uuid,
            commit_sha=ctx.commit_sha,
            body=body,
            body_markdown=body_markdown,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(
            "page_version_record_failed",
            page_id=page_id,
            error=str(exc),
        )


async def _record_symbols_for_page(
    env: env_mod.DocGenEnv,
    generation_id: str,
    page_id: str,
    page: DocPage,
) -> None:
    """Best-effort wrapper around ``storage.record_page_symbols``.

    Failure here must never break finalize — a missing link map only
    degrades the UX, it doesn't lose the page itself.
    """
    storage = env.storage
    if not hasattr(storage, "record_page_symbols"):
        return
    try:
        symbols = extract_page_symbols(page)
        if not symbols:
            return
        await storage.record_page_symbols(UUID(generation_id), page_id, symbols)
    except Exception as exc:
        logger.warning(
            "page_symbols_record_failed",
            page_id=page_id,
            error=str(exc),
        )


def extract_page_link_candidates(page: DocPage) -> list[str]:
    """Return backticked tokens from ``page`` body that *might* resolve to
    another page via ``lookup_page_for_symbol``.

    Re-uses the same regex extractor as ``extract_page_symbols`` but keeps
    every backtick token (not just CamelCase / snake_case_with_parens):
    page titles like ``Architecture`` or ``Boxed Mode`` won't match the
    identifier classifier yet still need to be resolvable as link
    targets. Stopwords and tiny tokens are dropped to keep the lookup
    set bounded; deduplication happens here so the caller doesn't have
    to issue redundant DB lookups.
    """
    seen: set[str] = set()
    candidates: list[str] = []
    for text in _iter_block_text(page.blocks):
        for match in _BACKTICK_RE.finditer(text):
            raw = match.group(1).strip()
            # Strip trailing parens for func-call-shaped mentions so
            # ``record_page_links()`` resolves the same as
            # ``record_page_links``.
            token = raw.split("(")[0].strip()
            if not token or len(token) < 3 or len(token) > 80:
                continue
            if token.lower() in _STOPWORDS:
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(token)
    return candidates


async def _record_links_for_page(
    env: env_mod.DocGenEnv,
    generation_id: str,
    page_id: str,
    page: DocPage,
) -> None:
    """Build the per-page outbound edge list and persist it.

    Algorithm (B13.2):

    1. Pull every backticked token from ``page`` (skipping stopwords).
    2. For each candidate, ask the storage layer to resolve it to a home
       page via ``lookup_page_for_symbol``; this re-uses the index
       written by B6.2's ``record_page_symbols`` step.
    3. If the resolved page is *another* page, accumulate an edge
       ``(page_id → resolved, kind='symbol', weight=mentions)``.
    4. Cap at ``_MAX_EDGES_PER_PAGE`` and bulk-upsert via
       ``record_page_links``.

    Self-loops are dropped. Failures are logged but never break finalize
    — a missing edge only degrades the wiki's "Referenced by" panel.
    """
    storage = env.storage
    if not hasattr(storage, "lookup_page_for_symbol") or not hasattr(storage, "record_page_links"):
        return
    try:
        candidates = extract_page_link_candidates(page)
        if not candidates:
            return

        gen_uuid = UUID(generation_id)
        # symbol mentions -> count, so duplicates accumulate weight.
        edges_by_target: dict[str, int] = {}
        for symbol in candidates:
            resolved = await storage.lookup_page_for_symbol(gen_uuid, symbol)
            if resolved is None:
                continue
            target_page_id, _kind = resolved
            if target_page_id == page_id:
                continue
            edges_by_target[target_page_id] = edges_by_target.get(target_page_id, 0) + 1

        if not edges_by_target:
            return

        # Cap edges per page to avoid pathological pages saturating the
        # table. Stable order (by descending weight) means the cap drops
        # the weakest edges first.
        sorted_edges = sorted(edges_by_target.items(), key=lambda kv: (-kv[1], kv[0]))
        capped = sorted_edges[:_MAX_EDGES_PER_PAGE]

        entries = [
            PageLinkEntry(
                from_page_id=page_id,
                to_page_id=target,
                kind="symbol",
                weight=weight,
            )
            for target, weight in capped
        ]
        await storage.record_page_links(gen_uuid, entries)
    except Exception as exc:
        logger.warning(
            "page_links_record_failed",
            page_id=page_id,
            error=str(exc),
        )


def _is_empty_page(page: DocPage) -> bool:
    """A page is empty when the writer opted out via the ``<no_content/>``
    sentinel (anti-hallucination shortcut) or produced no body content."""
    summary = (page.summary or "").lstrip()
    if summary.startswith("<no_content/>"):
        return True
    return not page.blocks


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    page_id = data["page_id"]
    page_data = data["page"]
    final_score = data.get("final_score", 0)
    review_summary = data.get("review_summary", "")

    page = DocPage(**page_data)

    if _is_empty_page(page):
        # Writer correctly bailed out instead of fabricating content for a
        # topic missing from the corpus. Mark the page as skipped so the
        # bundle finalizes cleanly without a placeholder row in Postgres.
        logger.info("page_skipped_empty", page_id=page_id)
        ctx.record_failed_page(page_id, "skipped_no_content")

        if ctx.bundle_id is not None and hasattr(env.storage, "mark_page_failed"):
            try:
                await env.storage.mark_page_failed(
                    ctx.bundle_id, page_id, "no_content", title=page.title or page_id
                )
            except Exception as exc:
                logger.warning(
                    "page_skip_persist_failed",
                    page_id=page_id,
                    error=str(exc),
                )

        await env.event_bus.emit(
            "doc.page.failed",
            {
                "generation_id": generation_id,
                "page_id": page_id,
                "bundle_id": ctx.bundle_id,
                "phase": "write",
                "error": "no_content",
                "error_type": "EmptyPageSkipped",
            },
        )

        if ctx.is_complete():
            await _finalize_generation(env, ctx, generation_id)
        return

    if ctx.bundle_id is not None:
        # B2.4 / iterative-mode classifier: persist the union of files this
        # writer-run touched (read_file + search_code hits + author-supplied
        # source_refs). Empty list → NULL in the column, which the
        # classifier treats as "unknown coverage" and skips for incremental
        # rebuilds (safer to re-write than misclassify as unaffected).
        page_source_files = ctx.page_source_files.get(page_id) or None
        await env.storage.write_page(
            ctx.bundle_id,
            page_id,
            page,
            commit_sha=ctx.commit_sha,
            source_files=page_source_files,
        )
        # B6.2 — cross-page link index; best-effort, failures are logged.
        await _record_symbols_for_page(env, generation_id, page_id, page)
        # B13.2 / ТЗ АГТ-06 — directed page-link graph; best-effort.
        # Must run after ``_record_symbols_for_page`` so this page's own
        # symbols are resolvable when a later page links back to it.
        await _record_links_for_page(env, generation_id, page_id, page)
        # B11.2 / ТЗ ГЕН-08 — append-only version history; best-effort,
        # failures are logged but do not abort the bundle.
        await _record_page_version(env, ctx, generation_id, page_id, page)

    logger.info("page_saved", page_id=page_id, score=final_score, summary=review_summary)

    await env.event_bus.emit(
        "doc.page.created",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "bundle_id": ctx.bundle_id,
            "score": final_score,
        },
    )

    ctx.record_page(page_id, page)

    completed_count = len(ctx.completed_pages)
    logger.info(
        "page_completed",
        page_id=page_id,
        completed=completed_count,
        total=ctx.expected_pages,
    )

    if ctx.is_complete():
        await _finalize_generation(env, ctx, generation_id)


async def handle_failed(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    """Record a per-page failure without aborting the rest of the bundle.

    Mirrors ``handle`` for the failure path: bumps the page accounting,
    persists a failure marker (so the UI can surface it next to the page),
    and triggers the bundle finalize when all pages are accounted for.
    """

    generation_id = data["generation_id"]
    page_id = data["page_id"]
    error = data.get("error", "unknown")
    error_type = data.get("error_type", "unknown")
    phase = data.get("phase", "write")

    ctx.record_failed_page(page_id, error)

    logger.warning(
        "page_failed",
        page_id=page_id,
        phase=phase,
        error=error,
        error_type=error_type,
        completed=len(ctx.completed_pages),
        failed=len(ctx.failed_pages),
        total=ctx.expected_pages,
    )

    if ctx.bundle_id is not None and hasattr(env.storage, "mark_page_failed"):
        try:
            await env.storage.mark_page_failed(ctx.bundle_id, page_id, error)
        except Exception as exc:
            logger.warning(
                "page_failure_persist_failed",
                page_id=page_id,
                error=str(exc),
            )

    await env.event_bus.emit(
        "doc.page.failed",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "bundle_id": ctx.bundle_id,
            "phase": phase,
            "error": error,
            "error_type": error_type,
        },
    )

    if ctx.is_complete():
        await _finalize_generation(env, ctx, generation_id)


async def _finalize_generation(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    generation_id: str,
) -> None:
    completed_count = len(ctx.completed_pages)
    failed_count = len(ctx.failed_pages)
    logger.info(
        "all_pages_resolved",
        completed=completed_count,
        failed=failed_count,
        total=ctx.expected_pages,
    )

    bundle_id = ctx.bundle_id
    failed_pages = dict(ctx.failed_pages)
    ctx.cleanup()

    await env.event_bus.emit(
        "generation.completed",
        {
            "generation_id": generation_id,
            "bundle_id": bundle_id,
            "pages_count": completed_count,
            "failed_pages_count": failed_count,
            "failed_pages": failed_pages,
        },
    )
