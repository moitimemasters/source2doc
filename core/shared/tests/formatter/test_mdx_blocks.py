"""DocBlock -> Markdown conversion tests.

PMI-mapping: 6.2.6 (Экспорт бандла документации, формат MkDocs) and 6.2.7
(Веб-интерфейс просмотра документации, рендеринг блоков). The shared
formatter is the only place where DocBlock variants become user-visible
markdown — every block type must round-trip through it cleanly.
"""

from source2doc.formatter.mdx import blocks as mdx_blocks
from source2doc.models import docs as doc_models


def test_heading_renders_correct_pound_count() -> None:
    out = mdx_blocks.format_block(doc_models.HeadingBlock(level=3, text="API"))
    assert out == ["### API"]


def test_paragraph_passes_through() -> None:
    out = mdx_blocks.format_block(doc_models.ParagraphBlock(text="Hello *world*"))
    assert out == ["Hello *world*"]


def test_code_block_uses_fenced_lang() -> None:
    out = mdx_blocks.format_block(
        doc_models.CodeBlock(lang="python", code="x = 1\nprint(x)")
    )
    assert out == ["```python", "x = 1\nprint(x)", "```"]


def test_unordered_list_uses_dashes() -> None:
    block = doc_models.ListBlock(
        ordered=False,
        items=[doc_models.ListItem(text="alpha"), doc_models.ListItem(text="beta")],
    )
    assert mdx_blocks.format_block(block) == ["- alpha", "- beta"]


def test_ordered_list_uses_numbers() -> None:
    block = doc_models.ListBlock(
        ordered=True,
        items=[doc_models.ListItem(text="alpha"), doc_models.ListItem(text="beta")],
    )
    assert mdx_blocks.format_block(block) == ["1. alpha", "2. beta"]


def test_table_renders_pipe_grid() -> None:
    block = doc_models.TableBlock(
        headers=["A", "B"],
        rows=[["1", "2"], ["3", "4"]],
    )
    out = mdx_blocks.format_block(block)
    assert out == [
        "| A | B |",
        "| --- | --- |",
        "| 1 | 2 |",
        "| 3 | 4 |",
    ]


def test_callout_includes_variant_label() -> None:
    block = doc_models.CalloutBlock(variant="warning", text="Be careful")
    out = mdx_blocks.format_block(block)
    assert any("WARNING" in line for line in out)
    assert any("Be careful" in line for line in out)


def test_mermaid_uses_fenced_mermaid() -> None:
    block = doc_models.MermaidBlock(diagram="graph TD; A-->B")
    out = mdx_blocks.format_block(block)
    assert out[0] == "```mermaid"
    assert out[-1] == "```"
    assert "graph TD; A-->B" in out


def test_cut_renders_collapsible_details() -> None:
    inner = doc_models.ParagraphBlock(text="hidden")
    block = doc_models.CutBlock(title="Click me", default_open=False, blocks=[inner])
    out = mdx_blocks.format_block(block)
    assert out[0] == "<details>"
    assert "<summary>Click me</summary>" in out
    assert out[-1] == "</details>"


def test_cut_default_open_emits_open_attr() -> None:
    block = doc_models.CutBlock(title="t", default_open=True, blocks=[])
    out = mdx_blocks.format_block(block)
    assert out[0] == "<details open>"


def test_image_renders_with_alt_and_caption() -> None:
    block = doc_models.ImageBlock(src="/x.png", alt="diagram", caption="Figure 1")
    out = mdx_blocks.format_block(block)
    assert out[0].startswith("![diagram](/x.png)")
    assert "Figure 1" in out[0]
