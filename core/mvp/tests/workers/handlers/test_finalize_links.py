"""Page-link recording tests for the finalize handler (B13.2 / ТЗ АГТ-06).

After a page is persisted and its symbols are recorded, the handler
walks the body for backticked tokens, resolves each via
``lookup_page_for_symbol``, and writes outbound edges to ``page_links``.
This file verifies the per-page edge-extraction algorithm:

  * Self-loops are dropped (``page_id == resolved_page``).
  * Duplicate mentions accumulate weight via ``edges_by_target``.
  * Failures inside the storage path are swallowed (best-effort).
  * The ``_MAX_EDGES_PER_PAGE`` cap is enforced.
  * Storage backends without ``record_page_links`` are tolerated.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from source2doc.models.docs import (
    DocPage,
    HeadingBlock,
    PageMetadata,
    ParagraphBlock,
)
from source2doc.storage.postgres import PageLinkEntry

from docgen_core.workers.handlers.finalize import (
    _MAX_EDGES_PER_PAGE,
    _record_links_for_page,
    extract_page_link_candidates,
)


GEN_ID = "11111111-2222-3333-4444-555555555555"


def _page(blocks: list, title: str = "Architecture") -> DocPage:
    return DocPage(
        title=title,
        summary="Test page",
        metadata=PageMetadata(),
        blocks=blocks,
    )


def test_extract_link_candidates_keeps_camelcase_and_func_calls() -> None:
    page = _page(
        blocks=[
            ParagraphBlock(
                text="See `DocPage` and call `record_page_symbols(...)` after `write_page()`."
            )
        ]
    )
    candidates = extract_page_link_candidates(page)
    # Parens stripped for resolution; lookup is case-insensitive on the
    # storage side anyway.
    assert "DocPage" in candidates
    assert "record_page_symbols" in candidates
    assert "write_page" in candidates


def test_extract_link_candidates_keeps_plain_title_phrases() -> None:
    """Page titles like ``Boxed Mode`` must be candidates even though
    they don't match the identifier classifier — the storage map carries
    them under ``page_title``.
    """
    page = _page(blocks=[ParagraphBlock(text="See `Boxed Mode` and `Architecture`.")])
    candidates = extract_page_link_candidates(page)
    assert "Boxed Mode" in candidates
    assert "Architecture" in candidates


def test_extract_link_candidates_drops_stopwords_and_short_tokens() -> None:
    page = _page(blocks=[ParagraphBlock(text="See `the` and `is` plus `OK`.")])
    candidates = extract_page_link_candidates(page)
    assert candidates == []


def test_extract_link_candidates_dedupes_case_insensitively() -> None:
    page = _page(
        blocks=[
            ParagraphBlock(text="See `DocPage` and `docpage` and `DOCPAGE`."),
        ]
    )
    candidates = extract_page_link_candidates(page)
    # First-seen casing wins; only one entry survives.
    assert candidates == ["DocPage"]


@pytest.mark.asyncio
async def test_record_links_writes_resolved_edges_only() -> None:
    """Tokens that don't resolve are skipped silently."""
    storage = MagicMock()
    # Two backticked tokens; one resolves, one doesn't.
    resolved: dict[str, tuple[str, str] | None] = {
        "DocPage": ("models", "class"),
        "MissingThing": None,
    }

    async def fake_lookup(_gen: UUID, symbol: str) -> tuple[str, str] | None:
        return resolved.get(symbol)

    storage.lookup_page_for_symbol = AsyncMock(side_effect=fake_lookup)
    storage.record_page_links = AsyncMock(return_value=None)

    env = MagicMock()
    env.storage = storage

    page = _page(blocks=[ParagraphBlock(text="See `DocPage` and `MissingThing` for details.")])
    await _record_links_for_page(env, GEN_ID, "overview", page)

    storage.record_page_links.assert_awaited_once()
    args = storage.record_page_links.await_args.args
    assert args[0] == UUID(GEN_ID)
    edges = args[1]
    assert edges == [
        PageLinkEntry(from_page_id="overview", to_page_id="models", kind="symbol", weight=1),
    ]


@pytest.mark.asyncio
async def test_record_links_drops_self_loops() -> None:
    """A symbol that resolves to the current page must not yield an edge."""
    storage = MagicMock()
    storage.lookup_page_for_symbol = AsyncMock(return_value=("overview", "page_title"))
    storage.record_page_links = AsyncMock(return_value=None)

    env = MagicMock()
    env.storage = storage

    page = _page(blocks=[ParagraphBlock(text="See `Overview` for details.")])
    await _record_links_for_page(env, GEN_ID, "overview", page)

    storage.record_page_links.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_links_aggregates_weight_for_repeat_mentions() -> None:
    """Multiple distinct candidates pointing at the same page bump weight.

    The candidate list itself is deduped (case-insensitive), so weight
    accumulates only when *different* symbols (e.g. a class and an alias
    or method) resolve to the same target page.
    """
    storage = MagicMock()
    storage.lookup_page_for_symbol = AsyncMock(side_effect=lambda _gen, sym: ("models", "class"))
    storage.record_page_links = AsyncMock(return_value=None)

    env = MagicMock()
    env.storage = storage

    page = _page(
        blocks=[
            ParagraphBlock(text="See `DocPage`, `PageMetadata`, and `BlockTypes`."),
        ]
    )
    await _record_links_for_page(env, GEN_ID, "overview", page)

    edges = storage.record_page_links.await_args.args[1]
    assert len(edges) == 1
    assert edges[0].to_page_id == "models"
    assert edges[0].weight == 3  # three distinct candidates, all mapped to "models"


@pytest.mark.asyncio
async def test_record_links_swallows_storage_errors() -> None:
    """Storage failures must not propagate to the caller."""
    storage = MagicMock()
    storage.lookup_page_for_symbol = AsyncMock(return_value=("models", "class"))
    storage.record_page_links = AsyncMock(side_effect=RuntimeError("postgres down"))

    env = MagicMock()
    env.storage = storage

    page = _page(blocks=[ParagraphBlock(text="See `DocPage` for details.")])
    # No exception should escape.
    await _record_links_for_page(env, GEN_ID, "overview", page)


@pytest.mark.asyncio
async def test_record_links_skipped_when_storage_lacks_method() -> None:
    """Older / fake storage backends without the new methods are tolerated."""
    storage = MagicMock(spec=[])  # nothing
    env = MagicMock()
    env.storage = storage

    page = _page(blocks=[ParagraphBlock(text="See `DocPage` for details.")])
    # Just must not raise.
    await _record_links_for_page(env, GEN_ID, "overview", page)


@pytest.mark.asyncio
async def test_record_links_caps_outbound_edges() -> None:
    """``_MAX_EDGES_PER_PAGE`` keeps pathological pages bounded."""
    storage = MagicMock()
    # Build (cap + 5) distinct symbols, each pointing to its own page.
    total = _MAX_EDGES_PER_PAGE + 5

    def fake_lookup(_gen: UUID, sym: str) -> tuple[str, str] | None:
        # Every symbol resolves to a unique target page derived from the symbol.
        return (f"page_{sym.lower()}", "class")

    storage.lookup_page_for_symbol = AsyncMock(side_effect=fake_lookup)
    storage.record_page_links = AsyncMock(return_value=None)

    env = MagicMock()
    env.storage = storage

    text = " ".join(f"`Symbol{idx:04d}`" for idx in range(total))
    page = _page(blocks=[ParagraphBlock(text=text), HeadingBlock(level=2, text="Refs")])
    await _record_links_for_page(env, GEN_ID, "overview", page)

    edges = storage.record_page_links.await_args.args[1]
    assert len(edges) == _MAX_EDGES_PER_PAGE
