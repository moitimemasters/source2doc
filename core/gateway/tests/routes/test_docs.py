"""Gateway /api/v1/docs/bundles/{generation_id}/pages/{page_id} tests.

Closes ТЗ ДОК-09 (B6.3) and ДОК-10 (B6.4) — verifies the page-detail
route exposes:

  * ``metadata.generated_at`` (sourced from ``documentation_pages.updated_at``)
  * ``metadata.llm_model`` (most-frequent ``generation_metrics.model``)
  * ``body_markdown`` (re-rendered GFM Markdown for the "Download MD" button)
  * ``repository.git_url`` / ``repository.commit_sha`` (already shipped in B11.1
    — re-asserted here so the contract doesn't regress when the metadata
    fields land).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from httpx import AsyncClient

from source2doc.models import docs as doc_models


GENERATION_ID = "11111111-2222-3333-4444-555555555555"
PAGE_ID = "overview"


def _make_page() -> doc_models.DocPage:
    """Build a typed ``DocPage`` covering a few block kinds.

    We pick blocks that exercise distinct branches of
    ``source2doc.formatter.mdx.blocks.format_block`` so the
    ``body_markdown`` assertion proves we're using the real renderer
    rather than a one-off stringify.
    """
    return doc_models.DocPage(
        title="Overview",
        summary="Short summary line.",
        metadata=doc_models.PageMetadata(
            generated_at="2026-05-05T10:00:00+00:00",
            reading_time=3,
            tags=["intro"],
            commit_sha="abc1234abc1234abc1234abc1234abc1234abcd",
        ),
        blocks=[
            doc_models.HeadingBlock(level=2, text="Hello"),
            doc_models.ParagraphBlock(text="World."),
            doc_models.CodeBlock(lang="python", code="print('hi')"),
        ],
        related=[],
    )


def _repo_info() -> dict:
    return {
        "name": "acme",
        "source_type": "git",
        "git_url": "https://github.com/acme/acme",
        "git_branch": "main",
        "commit_sha": "abc1234abc1234abc1234abc1234abc1234abcd",
    }


async def test_get_page_returns_404_for_missing_page(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    fake_storage.get_page = AsyncMock(return_value=None)
    response = await client.get(
        f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}",
    )
    assert response.status_code == 404


async def test_get_page_includes_generated_at_and_llm_model(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B6.3: page metadata carries the ISO date and dominant LLM model."""
    fake_storage.get_page = AsyncMock(return_value=_make_page())
    fake_storage.get_page_repository = AsyncMock(return_value=_repo_info())
    fake_storage.get_dominant_model = AsyncMock(return_value="claude-opus-4-7")

    response = await client.get(
        f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}",
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()

    metadata = body["metadata"]
    assert metadata["generated_at"] == "2026-05-05T10:00:00+00:00"
    assert metadata["llm_model"] == "claude-opus-4-7"
    # Existing fields stay intact (no regression on B11.1 / commit_sha).
    assert metadata["commit_sha"] == "abc1234abc1234abc1234abc1234abc1234abcd"
    assert body["repository"] == {
        "name": "acme",
        "source_type": "git",
        "git_url": "https://github.com/acme/acme",
        "git_branch": "main",
        "commit_sha": "abc1234abc1234abc1234abc1234abc1234abcd",
    }


async def test_get_page_handles_missing_metrics(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """``llm_model`` is ``None`` for legacy bundles with no metric rows."""
    fake_storage.get_page = AsyncMock(return_value=_make_page())
    fake_storage.get_page_repository = AsyncMock(return_value=None)
    fake_storage.get_dominant_model = AsyncMock(return_value=None)

    response = await client.get(
        f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["llm_model"] is None
    # B6.5: when there's no repository, the field is omitted entirely.
    assert "repository" not in body


async def test_get_page_renders_body_markdown(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B6.4: ``body_markdown`` is GFM rendered from the stored blocks."""
    fake_storage.get_page = AsyncMock(return_value=_make_page())
    fake_storage.get_page_repository = AsyncMock(return_value=None)
    fake_storage.get_dominant_model = AsyncMock(return_value=None)

    response = await client.get(
        f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}",
    )
    assert response.status_code == 200
    body_md = response.json()["body_markdown"]
    assert isinstance(body_md, str)
    # Title, summary, heading, paragraph, code fence — all rendered.
    assert body_md.startswith("# Overview")
    assert "Short summary line." in body_md
    assert "## Hello" in body_md
    assert "World." in body_md
    assert "```python" in body_md
    assert "print('hi')" in body_md


# ============================================================================
# B6.5 — repository (full shape) + source_refs round-trip
# ============================================================================


def _make_doc_page(*, source_refs: list[doc_models.SourceRef] | None = None) -> doc_models.DocPage:
    return doc_models.DocPage(
        title="Overview",
        summary="Test page",
        metadata=doc_models.PageMetadata(
            generated_at="2025-01-01T00:00:00Z",
            reading_time=2,
            tags=["intro"],
            source_refs=source_refs or [],
        ),
        blocks=[],
        related=[],
    )


async def test_get_page_includes_repository_with_commit_sha(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B6.5: repository (incl. commit_sha) and source_refs flow into the DTO."""
    fake_storage.get_page = AsyncMock(
        return_value=_make_doc_page(
            source_refs=[
                doc_models.SourceRef(file_path="src/foo.py", start_line=10, end_line=42),
            ]
        )
    )
    fake_storage.get_page_repository = AsyncMock(
        return_value={
            "name": "widget",
            "source_type": "git",
            "git_url": "https://github.com/acme/widget.git",
            "git_branch": "main",
            "commit_sha": "deadbeef",
        }
    )
    fake_storage.get_dominant_model = AsyncMock(return_value=None)

    response = await client.get(
        "/api/v1/docs/bundles/00000000-0000-0000-0000-000000000001/pages/overview"
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["title"] == "Overview"
    assert body["metadata"]["source_refs"] == [
        {"file_path": "src/foo.py", "start_line": 10, "end_line": 42}
    ]
    assert body["repository"] == {
        "name": "widget",
        "source_type": "git",
        "git_url": "https://github.com/acme/widget.git",
        "git_branch": "main",
        "commit_sha": "deadbeef",
    }


async def test_get_page_omits_repository_for_local_path_bundles(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B6.5: bundles without a repo row don't surface a ``repository`` key."""
    fake_storage.get_page = AsyncMock(return_value=_make_doc_page())
    fake_storage.get_page_repository = AsyncMock(return_value=None)
    fake_storage.get_dominant_model = AsyncMock(return_value=None)

    response = await client.get(
        "/api/v1/docs/bundles/00000000-0000-0000-0000-000000000002/pages/overview"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "repository" not in body
    assert body["metadata"]["source_refs"] == []


# ============================================================================
# B11.2 / ТЗ ГЕН-08 — page version history (list + get)
# ============================================================================


async def test_list_page_versions_returns_history_newest_first(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B11.2: ``/versions`` returns each snapshot with a 7-char short SHA."""
    from source2doc.storage.postgres import PageVersionMeta

    fake_storage.get_page = AsyncMock(return_value=_make_page())
    fake_storage.list_page_versions = AsyncMock(
        return_value=[
            PageVersionMeta(
                generation_id=UUID("11111111-2222-3333-4444-555555555556"),
                commit_sha="abcdef0123456789abcdef0123456789abcdef01",
                created_at="2026-05-05T12:00:00+00:00",
            ),
            PageVersionMeta(
                generation_id=UUID("11111111-2222-3333-4444-555555555555"),
                commit_sha=None,
                created_at="2026-05-04T08:00:00+00:00",
            ),
        ]
    )

    response = await client.get(f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}/versions")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["versions"]) == 2

    first = body["versions"][0]
    assert first["generation_id"] == "11111111-2222-3333-4444-555555555556"
    assert first["commit_sha"] == "abcdef0123456789abcdef0123456789abcdef01"
    assert first["short_sha"] == "abcdef0"
    assert first["created_at"] == "2026-05-05T12:00:00+00:00"

    second = body["versions"][1]
    assert second["commit_sha"] is None
    # Archive uploads with no SHA must report None for ``short_sha`` rather
    # than an empty string — the UI predicates on truthiness.
    assert second["short_sha"] is None


async def test_list_page_versions_returns_404_for_unknown_page(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B11.2: unknown page yields 404 before we hit the history table."""
    fake_storage.get_page = AsyncMock(return_value=None)
    fake_storage.list_page_versions = AsyncMock(return_value=[])

    response = await client.get(f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}/versions")
    assert response.status_code == 404
    # We must NOT reach the storage layer when the page is unknown — any
    # 404 must be raised before the DB call.
    fake_storage.list_page_versions.assert_not_called()


async def test_get_page_version_returns_full_snapshot(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B11.2: ``/versions/{id}`` returns the body + markdown for the snapshot."""
    from source2doc.storage.postgres import PageVersionDetail

    version_gen_id = UUID("99999999-aaaa-bbbb-cccc-dddddddddddd")
    fake_storage.get_page = AsyncMock(return_value=_make_page())
    fake_storage.get_page_version = AsyncMock(
        return_value=PageVersionDetail(
            page_id=PAGE_ID,
            generation_id=version_gen_id,
            repository_id=None,
            commit_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            body={
                "title": "Old Title",
                "summary": "Old summary.",
                "blocks": [
                    {"type": "paragraph", "text": "Historical body."},
                ],
                "related": ["intro"],
            },
            body_markdown="# Old Title\n\nOld summary.\n\nHistorical body.\n",
            metadata={"reading_time": 1, "tags": ["legacy"]},
            created_at="2026-04-01T09:00:00+00:00",
        )
    )

    response = await client.get(
        f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}/versions/{version_gen_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_id"] == PAGE_ID
    assert body["generation_id"] == str(version_gen_id)
    assert body["commit_sha"] == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert body["created_at"] == "2026-04-01T09:00:00+00:00"
    # Title/summary fall through from the snapshot body, not the latest row.
    assert body["title"] == "Old Title"
    assert body["summary"] == "Old summary."
    assert body["blocks"] == [{"type": "paragraph", "text": "Historical body."}]
    assert body["related"] == ["intro"]
    assert body["metadata"]["tags"] == ["legacy"]
    assert "Historical body." in body["body_markdown"]


async def test_get_page_version_returns_404_for_unknown_version(
    client: AsyncClient,
    fake_storage: MagicMock,
) -> None:
    """B11.2: missing snapshot yields 404 (page exists, version doesn't)."""
    version_gen_id = UUID("99999999-aaaa-bbbb-cccc-dddddddddddd")
    fake_storage.get_page = AsyncMock(return_value=_make_page())
    fake_storage.get_page_version = AsyncMock(return_value=None)

    response = await client.get(
        f"/api/v1/docs/bundles/{GENERATION_ID}/pages/{PAGE_ID}/versions/{version_gen_id}"
    )
    assert response.status_code == 404
