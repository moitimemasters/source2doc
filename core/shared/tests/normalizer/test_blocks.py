"""Tests for the deterministic block normalizer."""

from source2doc.models.docs import (
    CalloutBlock,
    CodeBlock,
    HeadingBlock,
    ListBlock,
    MermaidPlaceholderBlock,
    ParagraphBlock,
)
from source2doc.normalizer.blocks import normalize_blocks


def test_split_inline_heading_inside_paragraph() -> None:
    blocks = [
        ParagraphBlock(
            text="Intro text.\n## OAuth2 with Password Flow\nMore prose follows."
        ),
    ]

    out, report = normalize_blocks(blocks)

    assert report.inline_headings_split == 1
    assert len(out) == 3
    assert isinstance(out[0], ParagraphBlock) and out[0].text == "Intro text."
    assert isinstance(out[1], HeadingBlock)
    assert out[1].text == "OAuth2 with Password Flow"
    assert out[1].level == 2
    assert isinstance(out[2], ParagraphBlock) and out[2].text == "More prose follows."


def test_extract_fenced_code_from_paragraph() -> None:
    blocks = [
        ParagraphBlock(
            text="Use the helper:\n```python\ndef foo():\n    return 1\n```\nThat's it."
        ),
    ]

    out, report = normalize_blocks(blocks)

    assert report.fenced_code_extracted == 1
    types = [type(block).__name__ for block in out]
    assert "CodeBlock" in types
    code = next(b for b in out if isinstance(b, CodeBlock))
    assert code.lang == "python"
    assert "def foo()" in code.code


def test_extract_bullet_list_from_paragraph() -> None:
    blocks = [
        ParagraphBlock(text="- first\n- second\n- third"),
    ]

    out, report = normalize_blocks(blocks)

    assert report.inline_lists_extracted == 1
    assert len(out) == 1
    assert isinstance(out[0], ListBlock)
    assert out[0].ordered is False
    assert [item.text for item in out[0].items] == ["first", "second", "third"]


def test_normalize_heading_levels_demotes_skip() -> None:
    blocks = [
        HeadingBlock(level=1, text="Top"),
        HeadingBlock(level=4, text="Skipped"),
    ]

    out, report = normalize_blocks(blocks)

    assert report.heading_levels_normalized == 1
    assert isinstance(out[1], HeadingBlock)
    assert out[1].level == 2


def test_dead_mermaid_placeholder_replaced_with_callout() -> None:
    blocks = [
        MermaidPlaceholderBlock(
            placeholder_id="abc",
            kind="flowchart",
            intent="show data flow",
            anchors=[],
        )
    ]

    out, report = normalize_blocks(blocks)

    assert report.dead_placeholders_replaced == 1
    assert len(out) == 1
    assert isinstance(out[0], CalloutBlock)
    assert out[0].variant == "warning"
    assert "show data flow" in out[0].text


def test_clean_blocks_pass_through_with_zero_edits() -> None:
    blocks = [
        HeadingBlock(level=1, text="Title"),
        ParagraphBlock(text="Plain prose."),
        CodeBlock(lang="python", code="x = 1"),
    ]

    out, report = normalize_blocks(blocks)

    assert report.total == 0
    assert out == blocks
