"""Tests for the bundle Table of Contents autogenerator.

PMI-mapping: ТЗ ЭКС-08 — verifies that after formatter output the bundler
postprocessor produces ``toc.json`` and ``_toc.md`` files describing every
``.md``/``.mdx``/``.rst`` page in the bundle directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from worker.bundler import toc as toc_mod


# --------------------------------------------------------------------------- #
#                              extractors
# --------------------------------------------------------------------------- #


def test_extract_headings_md_skips_fences() -> None:
    text = "\n".join(
        [
            "# Real H1",
            "",
            "Some text.",
            "",
            "```python",
            "# not a heading",
            "## also not a heading",
            "```",
            "",
            "## Real H2",
            "",
            "~~~",
            "# fenced with tildes",
            "~~~",
            "",
            "### Too deep with default depth",
        ]
    )

    headings = toc_mod.extract_headings_from_md(text, max_depth=2)

    levels_and_text = [(h.level, h.text) for h in headings]
    assert levels_and_text == [(1, "Real H1"), (2, "Real H2")]
    assert headings[1].anchor == "real-h2"


def test_extract_headings_md_respects_max_depth() -> None:
    text = "# A\n## B\n### C\n#### D\n"
    headings = toc_mod.extract_headings_from_md(text, max_depth=3)
    assert [h.level for h in headings] == [1, 2, 3]


def test_extract_headings_md_max_depth_zero_returns_empty() -> None:
    assert toc_mod.extract_headings_from_md("# A\n## B", max_depth=0) == []


def test_extract_headings_rst_underline_style() -> None:
    text = "\n".join(
        [
            "Heading",
            "=======",
            "",
            "Some intro paragraph.",
            "",
            "Subheading",
            "----------",
            "",
            "Body.",
            "",
            "Another Sub",
            "-----------",
            "",
            "Deep",
            "~~~~",
        ]
    )

    headings = toc_mod.extract_headings_from_rst(text, max_depth=2)

    assert [(h.level, h.text) for h in headings] == [
        (1, "Heading"),
        (2, "Subheading"),
        (2, "Another Sub"),
    ]


def test_extract_headings_rst_requires_underline_at_least_as_long_as_title() -> None:
    text = "Heading\n==\n"  # underline shorter than title => not a section
    assert toc_mod.extract_headings_from_rst(text) == []


def test_slugify_handles_unicode_and_punctuation() -> None:
    assert toc_mod.slugify("Hello, World!") == "hello-world"
    assert toc_mod.slugify("  Leading and trailing  ") == "leading-and-trailing"
    assert toc_mod.slugify("foo_bar baz") == "foo-bar-baz"


# --------------------------------------------------------------------------- #
#                              build / write
# --------------------------------------------------------------------------- #


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_build_toc_writes_json_and_md(tmp_path: Path) -> None:
    _write(tmp_path / "index.md", "# Welcome\n\n## Overview\n")
    _write(
        tmp_path / "group" / "page1.md",
        "# Page One\n\n## Details\n\n### Too deep\n",
    )
    _write(tmp_path / "group" / "page2.md", "# Page Two\n\n## Other\n")
    # Files inside the skip-list must not appear.
    _write(tmp_path / "diagrams" / "g.md", "# Should be skipped\n")

    result = toc_mod.generate_toc_files(tmp_path, max_depth=2)

    assert result is not None
    paths = [e.path for e in result.entries]
    assert paths == ["group/page1.md", "group/page2.md", "index.md"]

    json_payload = json.loads((tmp_path / "toc.json").read_text(encoding="utf-8"))
    assert json_payload["max_depth"] == 2
    assert {e["path"] for e in json_payload["entries"]} == {
        "index.md",
        "group/page1.md",
        "group/page2.md",
    }
    # h3 should not leak into the entry headings since max_depth=2.
    page1_entry = next(e for e in json_payload["entries"] if e["path"] == "group/page1.md")
    assert all(h["level"] <= 2 for h in page1_entry["headings"])
    assert page1_entry["title"] == "Page One"

    md = (tmp_path / "_toc.md").read_text(encoding="utf-8")
    assert md.startswith("# Full Table of Contents")
    assert "[Welcome](./index.md)" in md
    assert "[Page One](./group/page1.md)" in md
    assert "[Overview](./index.md#overview)" in md
    # Diagrams content must not be referenced.
    assert "diagrams" not in md


def test_build_toc_disabled_when_max_depth_zero(tmp_path: Path) -> None:
    _write(tmp_path / "index.md", "# Welcome\n")
    result = toc_mod.generate_toc_files(tmp_path, max_depth=0)
    assert result is None
    assert not (tmp_path / "toc.json").exists()
    assert not (tmp_path / "_toc.md").exists()


def test_build_toc_handles_rst_files(tmp_path: Path) -> None:
    _write(
        tmp_path / "intro.rst",
        "Introduction\n============\n\nBody\n\nDetails\n-------\n",
    )
    toc = toc_mod.build_toc(tmp_path, max_depth=2)

    assert len(toc.entries) == 1
    entry = toc.entries[0]
    assert entry.path == "intro.rst"
    assert entry.title == "Introduction"
    assert [(h.level, h.text) for h in entry.headings] == [
        (1, "Introduction"),
        (2, "Details"),
    ]


def test_build_toc_skips_unreadable_files(tmp_path: Path) -> None:
    # Invalid UTF-8 bytes — extractor should swallow the decode error.
    (tmp_path / "broken.md").write_bytes(b"# title\n\xff\xfe not utf-8\n")
    _write(tmp_path / "ok.md", "# Ok\n")

    toc = toc_mod.build_toc(tmp_path, max_depth=2)

    paths = {e.path for e in toc.entries}
    assert "ok.md" in paths
    # broken.md is included but with no extracted headings.
    broken = next((e for e in toc.entries if e.path == "broken.md"), None)
    assert broken is not None
    assert broken.headings == []
