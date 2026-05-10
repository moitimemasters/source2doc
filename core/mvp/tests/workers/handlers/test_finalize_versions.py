"""Page-version recording tests for the finalize handler (B11.2 / ТЗ ГЕН-08).

After ``write_page`` persists the canonical row in ``documentation_pages``,
the handler also writes an append-only snapshot to ``page_versions`` so
the wiki UI can show "Versions ▾". This file verifies:

  * The markdown renderer on the snapshot agrees with the same renderer
    the gateway uses for the latest-page download (no drift).
  * The body dict carries title + summary so a historical view is
    self-contained even when a page is renamed between runs.
  * Failure inside ``record_page_version`` does not abort finalize —
    losing one history entry is degraded UX, not data loss.
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

from docgen_core.workers.context import GenerationContext
from docgen_core.workers.handlers.finalize import (
    _record_page_version,
    _render_page_markdown,
)


GEN_ID = "11111111-2222-3333-4444-555555555555"
REPO_ID = "22222222-3333-4444-5555-666666666666"


def _page() -> DocPage:
    return DocPage(
        title="Architecture",
        summary="High-level system map.",
        metadata=PageMetadata(reading_time=2, tags=["intro"]),
        blocks=[
            HeadingBlock(level=2, text="Components"),
            ParagraphBlock(text="See `Gateway` and `Worker` modules."),
        ],
    )


def test_render_page_markdown_includes_title_summary_and_blocks() -> None:
    md = _render_page_markdown(_page())
    assert md.startswith("# Architecture")
    assert "High-level system map." in md
    assert "## Components" in md
    assert "Gateway" in md and "Worker" in md


def test_render_page_markdown_appends_related_section() -> None:
    page = _page()
    page.related = ["overview", "deployment"]
    md = _render_page_markdown(page)
    assert "## Related Pages" in md
    assert "[overview](./overview.md)" in md
    assert "[deployment](./deployment.md)" in md


@pytest.mark.asyncio
async def test_record_page_version_writes_snapshot_with_self_contained_body() -> None:
    """Snapshot body must include title + summary even though the
    canonical ``documentation_pages.content`` row doesn't carry them —
    the historical view must render without consulting any other row.
    """
    storage = MagicMock()
    storage.record_page_version = AsyncMock(return_value=None)

    env = MagicMock()
    env.storage = storage

    ctx = GenerationContext(
        generation_id=GEN_ID,
        commit_sha="deadbeef" * 5,
        repository_id=REPO_ID,
    )

    await _record_page_version(env, ctx, GEN_ID, "architecture", _page())

    storage.record_page_version.assert_awaited_once()
    kwargs = storage.record_page_version.await_args.kwargs
    assert kwargs["page_id"] == "architecture"
    assert kwargs["generation_id"] == UUID(GEN_ID)
    assert kwargs["repository_id"] == UUID(REPO_ID)
    assert kwargs["commit_sha"] == "deadbeef" * 5

    body = kwargs["body"]
    assert body["title"] == "Architecture"
    assert body["summary"] == "High-level system map."
    assert any(block["type"] == "heading" for block in body["blocks"])

    body_md = kwargs["body_markdown"]
    assert "# Architecture" in body_md
    assert "## Components" in body_md


@pytest.mark.asyncio
async def test_record_page_version_swallows_storage_errors() -> None:
    """Failure to record a snapshot must not propagate — the canonical
    page row is already written before this is called.
    """
    storage = MagicMock()
    storage.record_page_version = AsyncMock(side_effect=RuntimeError("postgres down"))

    env = MagicMock()
    env.storage = storage

    ctx = GenerationContext(generation_id=GEN_ID)

    # No exception should escape — we just log and move on.
    await _record_page_version(env, ctx, GEN_ID, "architecture", _page())


@pytest.mark.asyncio
async def test_record_page_version_skipped_when_storage_lacks_method() -> None:
    """Older storage stubs (or alternate backends) without
    ``record_page_version`` must be tolerated — finalize is not the
    place to enforce a backend contract.
    """
    storage = MagicMock(spec=[])  # no methods at all
    env = MagicMock()
    env.storage = storage

    ctx = GenerationContext(generation_id=GEN_ID)
    await _record_page_version(env, ctx, GEN_ID, "architecture", _page())
