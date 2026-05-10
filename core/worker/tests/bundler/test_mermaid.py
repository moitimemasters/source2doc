"""Tests for the bundler Mermaid pre-rendering plumbing.

PMI-mapping: ТЗ ЭКС-07 — bundler can pre-render ```mermaid``` blocks to
SVG/PNG and replace the source fence with a static image reference, so the
exported bundle is consumable on platforms without a JS-side Mermaid
renderer (plain GFM viewers, Sphinx, PDF).

These tests mock out the actual ``mmdc`` shell-out via
``render_mermaid`` — the binary itself is verified separately at the
container-level (the worker Dockerfile installs ``@mermaid-js/mermaid-cli``
and ``chromium``).
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from source2doc.models import docs as doc_models

from worker.bundler import mermaid as mermaid_render
from worker.bundler.formatters import gfm, mkdocs, nextra, sphinx
from worker.bundler.formatters.gfm_formatter import GFMFormatter
from worker.bundler.formatters.mkdocs_formatter import MkDocsFormatter
from worker.bundler.formatters.nextra_formatter import NextraFormatter
from worker.bundler.formatters.sphinx_formatter import SphinxFormatter


def _page(diagram: str = "graph TD; A-->B") -> doc_models.DocPage:
    return doc_models.DocPage(
        title="Diagrammed",
        summary="Page with a diagram",
        metadata=doc_models.PageMetadata(
            generated_at=datetime.now(UTC).isoformat(),
            reading_time=1,
            tags=[],
        ),
        blocks=[
            doc_models.ParagraphBlock(text="Body."),
            doc_models.MermaidBlock(diagram=diagram),
        ],
    )


@pytest.fixture
def index_one() -> doc_models.DocIndex:
    return doc_models.DocIndex.create(navigation={"intro": "Intro"})


@pytest.fixture
def pages_one() -> dict[str, doc_models.DocPage]:
    return {"intro": _page()}


def _stub_render(
    monkeypatch: pytest.MonkeyPatch,
    *,
    succeed: bool = True,
) -> AsyncMock:
    """Replace ``render_mermaid`` with an async mock.

    On success it touches the target file (so ``prerender_mermaid_for_pages``
    treats the render as successful) and returns ``True``.
    """

    async def fake(diagram: str, out_path: Path, fmt: str) -> bool:
        if succeed:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"<svg/>")
            return True
        return False

    mock = AsyncMock(side_effect=fake)
    monkeypatch.setattr(mermaid_render, "render_mermaid", mock)
    return mock


# --------------------------------------------------------------------------- #
#                              Hashing & block walker
# --------------------------------------------------------------------------- #


def test_diagram_hash_is_deterministic_and_short() -> None:
    a = mermaid_render.diagram_hash("graph TD; A-->B")
    b = mermaid_render.diagram_hash("graph TD; A-->B")
    c = mermaid_render.diagram_hash("graph TD; A-->C")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_iter_mermaid_blocks_recurses_into_cut_blocks() -> None:
    inner = doc_models.MermaidBlock(diagram="inner")
    cut = doc_models.CutBlock(title="hidden", default_open=False, blocks=[inner])
    outer = doc_models.MermaidBlock(diagram="outer")
    found = list(mermaid_render._iter_mermaid_blocks([outer, cut]))
    assert {b.diagram for b in found} == {"outer", "inner"}


# --------------------------------------------------------------------------- #
#                              prerender_mermaid_for_pages
# --------------------------------------------------------------------------- #


async def test_prerender_no_op_for_fence_mode(tmp_path: Path) -> None:
    pages = {"intro": _page()}
    paths = await mermaid_render.prerender_mermaid_for_pages(pages, tmp_path, "fence")
    assert paths == {}
    # No mermaid/ directory should be created when not rendering.
    assert not (tmp_path / "mermaid").exists()


async def test_prerender_dedupes_diagrams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _stub_render(monkeypatch)
    pages = {
        "a": _page("graph TD; A-->B"),
        "b": _page("graph TD; A-->B"),  # identical → must dedupe
        "c": _page("graph TD; A-->C"),  # different → second render
    }
    paths = await mermaid_render.prerender_mermaid_for_pages(pages, tmp_path, "svg")
    assert mock.call_count == 2
    assert len(paths) == 2
    assert all(rel.startswith("mermaid/") and rel.endswith(".svg") for rel in paths.values())


async def test_prerender_falls_back_when_mmdc_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_render(monkeypatch, succeed=False)
    pages = {"intro": _page()}
    paths = await mermaid_render.prerender_mermaid_for_pages(pages, tmp_path, "svg")
    # Failed renders are dropped from the map → formatters fall back to fence.
    assert paths == {}


async def test_prerender_caps_diagrams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_render(monkeypatch)
    monkeypatch.setattr(mermaid_render, "MAX_DIAGRAMS_PER_BUNDLE", 3)

    pages = {f"page-{i}": _page(f"graph TD; A-->N{i}") for i in range(10)}
    paths = await mermaid_render.prerender_mermaid_for_pages(pages, tmp_path, "svg")
    # Cap bounds the number of distinct diagrams considered.
    assert len(paths) <= 3


# --------------------------------------------------------------------------- #
#                              GFM formatter integration
# --------------------------------------------------------------------------- #


async def test_gfm_keeps_fence_when_mode_is_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_one, pages_one
) -> None:
    mock = _stub_render(monkeypatch)
    formatter = GFMFormatter()
    await gfm.format_bundle(formatter, index_one, pages_one, tmp_path, "fence")

    body = (tmp_path / "intro.md").read_text(encoding="utf-8")
    assert "```mermaid" in body
    assert "![Mermaid diagram]" not in body
    mock.assert_not_called()


async def test_gfm_replaces_fence_with_image_when_mode_is_svg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_one, pages_one
) -> None:
    mock = _stub_render(monkeypatch)
    formatter = GFMFormatter()
    await gfm.format_bundle(formatter, index_one, pages_one, tmp_path, "svg")

    body = (tmp_path / "intro.md").read_text(encoding="utf-8")
    # Source fence is gone; image reference points into ./mermaid/.
    assert "```mermaid" not in body
    assert "![Mermaid diagram](./mermaid/" in body
    assert body.count(".svg)") == 1

    # The pre-render helper actually shelled out (mocked) for one diagram.
    assert mock.call_count == 1
    # Image artifact lives under the bundle root.
    rendered_files = list((tmp_path / "mermaid").glob("*.svg"))
    assert len(rendered_files) == 1


async def test_gfm_grouped_pages_use_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_render(monkeypatch)
    formatter = GFMFormatter()

    grouped_index = doc_models.DocIndex.create(
        navigation={
            "commands": {
                "title": "Commands",
                "children": {"find": "Find"},
            },
        }
    )
    grouped_pages = {"find": _page()}

    await gfm.format_bundle(formatter, grouped_index, grouped_pages, tmp_path, "svg")

    body = (tmp_path / "commands" / "find.md").read_text(encoding="utf-8")
    # Page is one level deep — must walk back up to the bundle root.
    assert "![Mermaid diagram](../mermaid/" in body


# --------------------------------------------------------------------------- #
#                              Sphinx formatter integration
# --------------------------------------------------------------------------- #


async def test_sphinx_emits_image_directive_on_svg_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_one, pages_one
) -> None:
    _stub_render(monkeypatch)
    formatter = SphinxFormatter()
    await sphinx.format_bundle(formatter, index_one, pages_one, tmp_path, "svg")

    body = (tmp_path / "intro.rst").read_text(encoding="utf-8")
    assert ".. mermaid::" not in body
    assert ".. image:: mermaid/" in body
    assert ".svg" in body


async def test_sphinx_keeps_directive_on_fence_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_one, pages_one
) -> None:
    mock = _stub_render(monkeypatch)
    formatter = SphinxFormatter()
    await sphinx.format_bundle(formatter, index_one, pages_one, tmp_path, "fence")

    body = (tmp_path / "intro.rst").read_text(encoding="utf-8")
    assert ".. mermaid::" in body
    mock.assert_not_called()


# --------------------------------------------------------------------------- #
#                              MkDocs / Nextra default to fence
# --------------------------------------------------------------------------- #


async def test_mkdocs_keeps_fence_when_mode_is_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_one, pages_one
) -> None:
    mock = _stub_render(monkeypatch)
    formatter = MkDocsFormatter()
    await mkdocs.format_bundle(formatter, index_one, pages_one, tmp_path, "fence")

    body = (tmp_path / "docs" / "intro.md").read_text(encoding="utf-8")
    assert "```mermaid" in body
    mock.assert_not_called()


async def test_nextra_keeps_fence_when_mode_is_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index_one, pages_one
) -> None:
    mock = _stub_render(monkeypatch)
    formatter = NextraFormatter()
    await nextra.format_bundle(formatter, index_one, pages_one, tmp_path, "fence")

    body = (tmp_path / "content" / "intro.mdx").read_text(encoding="utf-8")
    assert "```mermaid" in body
    mock.assert_not_called()


# --------------------------------------------------------------------------- #
#                              Processor → format selection
# --------------------------------------------------------------------------- #


def test_resolve_mermaid_mode_defaults_per_format() -> None:
    from worker.bundler.processor import _resolve_mermaid_mode

    assert _resolve_mermaid_mode(None, "gfm") == "svg"
    assert _resolve_mermaid_mode(None, "sphinx") == "svg"
    assert _resolve_mermaid_mode(None, "mkdocs") == "fence"
    assert _resolve_mermaid_mode(None, "nextra") == "fence"


def test_resolve_mermaid_mode_respects_explicit_request() -> None:
    from worker.bundler.processor import _resolve_mermaid_mode

    assert _resolve_mermaid_mode("fence", "gfm") == "fence"
    assert _resolve_mermaid_mode("png", "mkdocs") == "png"
    assert _resolve_mermaid_mode("svg", "nextra") == "svg"


def test_resolve_mermaid_mode_ignores_garbage_values() -> None:
    from worker.bundler.processor import _resolve_mermaid_mode

    assert _resolve_mermaid_mode("garbage", "gfm") == "svg"
    assert _resolve_mermaid_mode("", "mkdocs") == "fence"


# --------------------------------------------------------------------------- #
#                              render_mermaid: mmdc not installed
# --------------------------------------------------------------------------- #


async def test_render_mermaid_returns_false_when_mmdc_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``mmdc`` is not on PATH the helper logs a warning and returns False
    without raising, so callers cleanly fall back to the original fence."""

    async def fake_create(*args, **kwargs):
        raise FileNotFoundError("mmdc")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create,
    )

    out = tmp_path / "out.svg"
    ok = await mermaid_render.render_mermaid("graph TD; A-->B", out, "svg")
    assert ok is False
