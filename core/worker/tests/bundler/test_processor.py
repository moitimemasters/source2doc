"""End-to-end processor tests for the bundler worker.

PMI-mapping: 6.2.6 (Экспорт бандла документации). Drives ``_format_bundle``
through every supported format selector and verifies it raises on unknown
formats — the same contract the bundler stream consumer relies on.
"""

from pathlib import Path

import pytest

from source2doc.models import docs as doc_models

from worker.bundler.processor import _format_bundle


def _index() -> doc_models.DocIndex:
    return doc_models.DocIndex.create(navigation={"intro": "Intro"})


def _pages() -> dict[str, doc_models.DocPage]:
    return {
        "intro": doc_models.DocPage(
            title="Intro",
            summary="Summary",
            metadata=doc_models.PageMetadata(
                generated_at="2026-05-04T00:00:00Z",
                reading_time=1,
            ),
            blocks=[doc_models.ParagraphBlock(text="Hello")],
        )
    }


@pytest.mark.parametrize(
    "fmt,expected_marker",
    [
        ("mkdocs", "mkdocs.yml"),
        ("nextra", "next.config.mjs"),
        ("sphinx", "conf.py"),
        ("gfm", "README.md"),
        ("yfm", "toc.yaml"),
    ],
)
async def test_format_bundle_supported_formats(
    tmp_path: Path, fmt: str, expected_marker: str
) -> None:
    await _format_bundle(fmt, _index(), _pages(), tmp_path)
    assert (tmp_path / expected_marker).exists()


async def test_format_bundle_is_case_insensitive(tmp_path: Path) -> None:
    await _format_bundle("MkDocs", _index(), _pages(), tmp_path)
    assert (tmp_path / "mkdocs.yml").exists()


async def test_format_bundle_rejects_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported format"):
        await _format_bundle("docusaurus", _index(), _pages(), tmp_path)
