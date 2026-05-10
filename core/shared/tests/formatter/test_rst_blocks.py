"""DocBlock -> reStructuredText conversion tests.

PMI-mapping: 6.2.6 (Экспорт бандла документации, формат Sphinx).
"""

from source2doc.formatter.rst import blocks as rst_blocks
from source2doc.models import docs as doc_models


def test_heading_underline_matches_text_length() -> None:
    out = rst_blocks.format_block(doc_models.HeadingBlock(level=1, text="Intro"))
    assert out == ["Intro", "====="]


def test_code_block_uses_directive_with_indent() -> None:
    out = rst_blocks.format_block(
        doc_models.CodeBlock(lang="python", code="x = 1\nprint(x)")
    )
    assert out[0] == ".. code-block:: python"
    assert out[1] == ""
    assert out[2] == "   x = 1"
    assert out[3] == "   print(x)"


def test_callout_maps_variant_to_directive() -> None:
    cases: list[tuple[doc_models.CalloutBlock, str]] = [
        (doc_models.CalloutBlock(variant="info", text="msg"), "note"),
        (doc_models.CalloutBlock(variant="warning", text="msg"), "warning"),
        (doc_models.CalloutBlock(variant="error", text="msg"), "danger"),
        (doc_models.CalloutBlock(variant="success", text="msg"), "tip"),
    ]
    for block, directive in cases:
        out = rst_blocks.format_block(block)
        assert out[0] == f".. {directive}::"


def test_mermaid_uses_mermaid_directive() -> None:
    out = rst_blocks.format_block(doc_models.MermaidBlock(diagram="graph TD; A-->B"))
    assert out[0] == ".. mermaid::"
    assert out[1] == ""
    assert out[2] == "   graph TD; A-->B"


def test_table_uses_grid_borders() -> None:
    block = doc_models.TableBlock(headers=["A", "B"], rows=[["1", "2"]])
    out = rst_blocks.format_block(block)
    # Grid table starts with a separator line
    assert out[0].startswith("+") and out[0].endswith("+")
    # Header underline uses "="
    assert "=" in out[2]


def test_cut_uses_dropdown_directive() -> None:
    inner = doc_models.ParagraphBlock(text="nested")
    block = doc_models.CutBlock(title="Click", default_open=True, blocks=[inner])
    out = rst_blocks.format_block(block)
    assert out[0].startswith(".. dropdown:: Click")
    assert ":open: true" in out[1]


def test_image_includes_alt_and_caption() -> None:
    block = doc_models.ImageBlock(src="/x.png", alt="diagram", caption="Fig 1")
    out = rst_blocks.format_block(block)
    assert ".. image:: /x.png" in out
    assert any(":alt: diagram" in line for line in out)
    assert any("Fig 1" in line for line in out)
