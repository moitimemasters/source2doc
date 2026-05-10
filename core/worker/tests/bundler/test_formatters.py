"""End-to-end formatter tests against real templates and the filesystem.

PMI-mapping: 6.2.6 (Экспорт бандла документации) — verifies that for each
target format the bundler produces the documents expected by the PMI:

  * MkDocs   — ``.md`` pages, ``mkdocs.yml`` with nav, ``Dockerfile``.
  * Nextra   — ``.mdx`` pages, ``next.config.mjs``, ``Dockerfile``.
  * Sphinx   — ``.rst`` pages, ``conf.py``, ``Dockerfile``, ``index.rst``
               with ``toctree`` directive.
  * YFM      — ``.md`` pages, ``toc.yaml``, ``Dockerfile``; YFM-specific
               ``{% note %}`` and ``{% cut %}`` markup for callouts and
               collapsible sections (closes ТЗ ЭКС-04).
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from source2doc.models import docs as doc_models

from worker.bundler.formatters import gfm, mkdocs, nextra, sphinx, yfm
from worker.bundler.formatters.gfm_formatter import GFMFormatter
from worker.bundler.formatters.mkdocs_formatter import MkDocsFormatter
from worker.bundler.formatters.nextra_formatter import NextraFormatter
from worker.bundler.formatters.sphinx_formatter import SphinxFormatter
from worker.bundler.formatters.yfm_formatter import YFMFormatter


def _make_page(title: str, summary: str = "Page summary") -> doc_models.DocPage:
    return doc_models.DocPage(
        title=title,
        summary=summary,
        metadata=doc_models.PageMetadata(
            generated_at=datetime.now(timezone.utc).isoformat(),
            reading_time=2,
            tags=["example"],
        ),
        blocks=[
            doc_models.HeadingBlock(level=2, text="Section"),
            doc_models.ParagraphBlock(text="Body."),
            doc_models.CodeBlock(lang="python", code="x = 1"),
            doc_models.CalloutBlock(variant="info", text="A callout."),
            doc_models.MermaidBlock(diagram="graph TD; A-->B"),
        ],
    )


@pytest.fixture
def index() -> doc_models.DocIndex:
    return doc_models.DocIndex.create(
        navigation={
            "intro": "Introduction",
            "usage": "Usage",
        }
    )


@pytest.fixture
def pages() -> dict[str, doc_models.DocPage]:
    return {
        "intro": _make_page("Introduction"),
        "usage": _make_page("Usage"),
    }


# --------------------------------------------------------------------------- #
#                              mkdocs
# --------------------------------------------------------------------------- #


async def test_mkdocs_writes_md_pages(tmp_path: Path, index, pages) -> None:
    formatter = MkDocsFormatter()
    await mkdocs.format_bundle(formatter, index, pages, tmp_path)

    docs_dir = tmp_path / "docs"
    assert (docs_dir / "intro.md").exists()
    assert (docs_dir / "usage.md").exists()

    content = (docs_dir / "intro.md").read_text(encoding="utf-8")
    assert content.startswith("# Introduction")
    assert "```python" in content
    assert "```mermaid" in content


async def test_mkdocs_config_includes_navigation_and_dockerfile(
    tmp_path: Path, index, pages
) -> None:
    formatter = MkDocsFormatter()
    await mkdocs.format_bundle(formatter, index, pages, tmp_path)
    await mkdocs.generate_config(formatter, tmp_path, {"navigation": index.navigation})
    await mkdocs.generate_dockerfile(formatter, tmp_path)

    yml = (tmp_path / "mkdocs.yml").read_text(encoding="utf-8")
    assert "intro" in yml
    assert "usage" in yml
    assert (tmp_path / "Dockerfile").exists()
    assert (tmp_path / "requirements.txt").exists()


# --------------------------------------------------------------------------- #
#                              nextra
# --------------------------------------------------------------------------- #


async def test_nextra_writes_mdx_pages_and_meta(
    tmp_path: Path, index, pages
) -> None:
    formatter = NextraFormatter()
    await nextra.format_bundle(formatter, index, pages, tmp_path)

    content_dir = tmp_path / "content"
    assert (content_dir / "intro.mdx").exists()
    assert (content_dir / "usage.mdx").exists()
    # Implicit synthesised root index page.
    assert (content_dir / "index.mdx").exists()
    # Nextra v4 sidebar metadata.
    assert (content_dir / "_meta.js").exists()

    body = (content_dir / "intro.mdx").read_text(encoding="utf-8")
    assert body.startswith("---")
    assert "title: Introduction" in body
    assert "```mermaid" in body


async def test_nextra_config_emits_next_config_and_dockerfile(
    tmp_path: Path, index, pages
) -> None:
    formatter = NextraFormatter()
    await nextra.format_bundle(formatter, index, pages, tmp_path)
    await nextra.generate_config(
        formatter, tmp_path, {"project_name": "demo", "navigation": index.navigation}
    )
    await nextra.generate_dockerfile(formatter, tmp_path)

    assert (tmp_path / "next.config.mjs").exists()
    assert (tmp_path / "package.json").exists()
    assert (tmp_path / "mdx-components.js").exists()
    assert (tmp_path / "app" / "layout.jsx").exists()
    assert (tmp_path / "app" / "[[...mdxPath]]" / "page.jsx").exists()
    assert (tmp_path / "Dockerfile").exists()


async def test_nextra_groups_create_subdirectory_pages(tmp_path: Path) -> None:
    formatter = NextraFormatter()

    grouped_index = doc_models.DocIndex.create(
        navigation={
            "intro": "Introduction",
            "commands": {
                "title": "Commands",
                "children": {"find": "Find", "stop": "Stop"},
            },
        }
    )
    grouped_pages = {
        "intro": _make_page("Introduction"),
        "find": _make_page("Find"),
        "stop": _make_page("Stop"),
    }

    await nextra.format_bundle(formatter, grouped_index, grouped_pages, tmp_path)

    content_dir = tmp_path / "content"
    assert (content_dir / "commands" / "find.mdx").exists()
    assert (content_dir / "commands" / "stop.mdx").exists()
    # Synthesised group landing page.
    assert (content_dir / "commands" / "index.mdx").exists()
    # Group's own _meta.js for the sidebar.
    assert (content_dir / "commands" / "_meta.js").exists()


# --------------------------------------------------------------------------- #
#                              sphinx
# --------------------------------------------------------------------------- #


async def test_sphinx_writes_rst_pages_and_index(
    tmp_path: Path, index, pages
) -> None:
    formatter = SphinxFormatter()
    await sphinx.format_bundle(formatter, index, pages, tmp_path)

    assert (tmp_path / "intro.rst").exists()
    assert (tmp_path / "usage.rst").exists()

    index_rst = (tmp_path / "index.rst").read_text(encoding="utf-8")
    assert ".. toctree::" in index_rst
    assert "intro" in index_rst
    assert "usage" in index_rst

    body = (tmp_path / "intro.rst").read_text(encoding="utf-8")
    assert ".. code-block:: python" in body
    assert ".. note::" in body
    assert ".. mermaid::" in body


async def test_sphinx_config_and_dockerfile(
    tmp_path: Path, index, pages
) -> None:
    formatter = SphinxFormatter()
    await sphinx.format_bundle(formatter, index, pages, tmp_path)
    await sphinx.generate_config(
        formatter, tmp_path, {"project_name": "Demo Docs"}
    )
    await sphinx.generate_dockerfile(formatter, tmp_path)

    conf = (tmp_path / "conf.py").read_text(encoding="utf-8")
    assert "Demo Docs" in conf
    assert (tmp_path / "Dockerfile").exists()
    assert (tmp_path / "requirements.txt").exists()


# --------------------------------------------------------------------------- #
#                              gfm
# --------------------------------------------------------------------------- #


async def test_gfm_writes_md_pages_and_root_readme(tmp_path: Path, index, pages) -> None:
    formatter = GFMFormatter()
    await gfm.format_bundle(formatter, index, pages, tmp_path)

    assert (tmp_path / "intro.md").exists()
    assert (tmp_path / "usage.md").exists()
    assert (tmp_path / "README.md").exists()

    body = (tmp_path / "intro.md").read_text(encoding="utf-8")
    assert body.startswith("# Introduction")
    # Mermaid fences must remain intact for native github.com rendering.
    assert "```mermaid" in body
    assert "```python" in body

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    # Nested bullet list with relative links to pages.
    assert "- [Introduction](./intro.md)" in readme
    assert "- [Usage](./usage.md)" in readme


async def test_gfm_groups_create_subdirectories_with_readmes(
    tmp_path: Path,
) -> None:
    formatter = GFMFormatter()

    grouped_index = doc_models.DocIndex.create(
        navigation={
            "intro": "Introduction",
            "commands": {
                "title": "Commands",
                "children": {"find": "Find", "stop": "Stop"},
            },
        }
    )
    grouped_pages = {
        "intro": _make_page("Introduction"),
        "find": _make_page("Find"),
        "stop": _make_page("Stop"),
    }

    await gfm.format_bundle(formatter, grouped_index, grouped_pages, tmp_path)

    assert (tmp_path / "commands" / "find.md").exists()
    assert (tmp_path / "commands" / "stop.md").exists()
    # Per-group landing page (renders automatically on github.com).
    assert (tmp_path / "commands" / "README.md").exists()

    root_readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    # Group entry links to the group's README; children appear nested.
    assert "- [Commands](./commands/README.md)" in root_readme
    assert "  - [Find](./commands/find.md)" in root_readme
    assert "  - [Stop](./commands/stop.md)" in root_readme


async def test_gfm_skips_config_and_dockerfile(tmp_path: Path, index, pages) -> None:
    formatter = GFMFormatter()
    await gfm.format_bundle(formatter, index, pages, tmp_path)
    await gfm.generate_config(formatter, tmp_path, {})
    await gfm.generate_dockerfile(formatter, tmp_path)

    # Plain GFM bundles ship no config files.
    assert not (tmp_path / "Dockerfile").exists()
    assert not (tmp_path / "mkdocs.yml").exists()
    assert not (tmp_path / "next.config.mjs").exists()
    assert not (tmp_path / "conf.py").exists()


# --------------------------------------------------------------------------- #
#                              yfm
# --------------------------------------------------------------------------- #


async def test_yfm_writes_md_pages_and_index(tmp_path: Path, index, pages) -> None:
    formatter = YFMFormatter()
    await yfm.format_bundle(formatter, index, pages, tmp_path)

    assert (tmp_path / "intro.md").exists()
    assert (tmp_path / "usage.md").exists()
    # Synthesised root index page.
    assert (tmp_path / "index.md").exists()

    body = (tmp_path / "intro.md").read_text(encoding="utf-8")
    assert body.startswith("# Introduction")
    assert "```python" in body
    assert "```mermaid" in body


async def test_yfm_callouts_become_note_blocks(tmp_path: Path) -> None:
    formatter = YFMFormatter()

    page = doc_models.DocPage(
        title="Notes",
        summary="Demo of admonitions",
        metadata=doc_models.PageMetadata(
            generated_at=datetime.now(timezone.utc).isoformat(),
            reading_time=1,
        ),
        blocks=[
            doc_models.CalloutBlock(variant="info", text="Heads up."),
            doc_models.CalloutBlock(variant="warning", text="Careful here."),
            doc_models.CalloutBlock(variant="success", text="Nice."),
            doc_models.CalloutBlock(variant="error", text="Boom."),
        ],
    )
    idx = doc_models.DocIndex.create(navigation={"notes": "Notes"})

    await yfm.format_bundle(formatter, idx, {"notes": page}, tmp_path)

    body = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert "{% note info %}" in body
    assert "{% note warning %}" in body
    assert "{% note tip %}" in body  # success -> tip
    assert "{% note alert %}" in body  # error -> alert
    assert "{% endnote %}" in body
    assert "Heads up." in body


async def test_yfm_cut_blocks_become_cut_markup(tmp_path: Path) -> None:
    formatter = YFMFormatter()

    page = doc_models.DocPage(
        title="Folded",
        summary="Demo of cuts",
        metadata=doc_models.PageMetadata(
            generated_at=datetime.now(timezone.utc).isoformat(),
            reading_time=1,
        ),
        blocks=[
            doc_models.CutBlock(
                title="Click to expand",
                blocks=[
                    doc_models.ParagraphBlock(text="Hidden body."),
                    doc_models.CodeBlock(lang="python", code="print('hi')"),
                ],
            ),
        ],
    )
    idx = doc_models.DocIndex.create(navigation={"folded": "Folded"})

    await yfm.format_bundle(formatter, idx, {"folded": page}, tmp_path)

    body = (tmp_path / "folded.md").read_text(encoding="utf-8")
    assert '{% cut "Click to expand" %}' in body
    assert "{% endcut %}" in body
    assert "Hidden body." in body
    assert "```python" in body  # nested code block survived


async def test_yfm_toc_yaml_is_valid_and_lists_pages(
    tmp_path: Path, index, pages
) -> None:
    formatter = YFMFormatter()
    await yfm.format_bundle(formatter, index, pages, tmp_path)
    await yfm.generate_config(
        formatter,
        tmp_path,
        {
            "site_name": "Demo Docs",
            "navigation": index.navigation,
            "pages": pages,
        },
    )
    await yfm.generate_dockerfile(formatter, tmp_path)

    toc_path = tmp_path / "toc.yaml"
    assert toc_path.exists()
    assert (tmp_path / "Dockerfile").exists()

    toc = yaml.safe_load(toc_path.read_text(encoding="utf-8"))
    assert toc["title"] == "Demo Docs"
    hrefs = [item["href"] for item in toc["items"] if "href" in item]
    assert "intro.md" in hrefs
    assert "usage.md" in hrefs


async def test_yfm_groups_create_subdirectory_pages_and_nested_toc(
    tmp_path: Path,
) -> None:
    formatter = YFMFormatter()

    grouped_index = doc_models.DocIndex.create(
        navigation={
            "intro": "Introduction",
            "commands": {
                "title": "Commands",
                "children": {"find": "Find", "stop": "Stop"},
            },
        }
    )
    grouped_pages = {
        "intro": _make_page("Introduction"),
        "find": _make_page("Find"),
        "stop": _make_page("Stop"),
    }

    await yfm.format_bundle(formatter, grouped_index, grouped_pages, tmp_path)
    await yfm.generate_config(
        formatter,
        tmp_path,
        {
            "site_name": "Grouped",
            "navigation": grouped_index.navigation,
            "pages": grouped_pages,
        },
    )

    assert (tmp_path / "commands" / "find.md").exists()
    assert (tmp_path / "commands" / "stop.md").exists()
    assert (tmp_path / "commands" / "index.md").exists()

    toc = yaml.safe_load((tmp_path / "toc.yaml").read_text(encoding="utf-8"))
    group_entries = [item for item in toc["items"] if "items" in item]
    assert any(g["name"] == "Commands" for g in group_entries)
    commands = next(g for g in group_entries if g["name"] == "Commands")
    child_hrefs = [c["href"] for c in commands["items"] if "href" in c]
    assert "commands/find.md" in child_hrefs
    assert "commands/stop.md" in child_hrefs
