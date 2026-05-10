from source2doc.models import docs as doc_models


def format_block(
    block: doc_models.DocBlock,
    mermaid_image_paths: dict[str, str] | None = None,
) -> list[str]:
    """Render a single :class:`DocBlock` into reStructuredText lines.

    ``mermaid_image_paths`` (optional) maps a Mermaid diagram body to a
    bundle-relative image path. When a mermaid block's diagram text is in
    the map, the ``.. mermaid::`` directive is replaced with a static
    ``.. image::`` reference. Otherwise the original directive is emitted.
    """
    match block:
        case doc_models.HeadingBlock():
            return _format_heading(block)
        case doc_models.ParagraphBlock():
            return _format_paragraph(block)
        case doc_models.CodeBlock():
            return _format_code(block)
        case doc_models.ListBlock():
            return _format_list(block)
        case doc_models.TableBlock():
            return _format_table(block)
        case doc_models.CalloutBlock():
            return _format_callout(block)
        case doc_models.MermaidBlock():
            return _format_mermaid(block, mermaid_image_paths)
        case doc_models.CutBlock():
            return _format_cut(block, mermaid_image_paths)
        case doc_models.ImageBlock():
            return _format_image(block)
        case _:
            return []


def _format_heading(block: doc_models.HeadingBlock) -> list[str]:
    underline_chars = ["=", "-", "~", "^", '"', "'"]
    char = underline_chars[min(block.level - 1, len(underline_chars) - 1)]
    underline = char * len(block.text)
    return [block.text, underline]


def _format_paragraph(block: doc_models.ParagraphBlock) -> list[str]:
    return [block.text]


def _format_code(block: doc_models.CodeBlock) -> list[str]:
    lines = [f".. code-block:: {block.lang}", ""]
    for line in block.code.split("\n"):
        lines.append(f"   {line}")
    return lines


def _format_list(block: doc_models.ListBlock) -> list[str]:
    lines = []
    for idx, item in enumerate(block.items):
        if block.ordered:
            lines.append(f"{idx + 1}. {item.text}")
        else:
            lines.append(f"* {item.text}")
    return lines


def _format_table(block: doc_models.TableBlock) -> list[str]:
    col_widths = [len(h) for h in block.headers]
    for row in block.rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    lines = []

    separator = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    lines.append(separator)

    header_line = (
        "|" + "|".join(f" {h:<{col_widths[i]}} " for i, h in enumerate(block.headers)) + "|"
    )
    lines.append(header_line)
    lines.append(separator.replace("-", "="))

    for row in block.rows:
        row_line = "|" + "|".join(f" {cell:<{col_widths[i]}} " for i, cell in enumerate(row)) + "|"
        lines.append(row_line)
        lines.append(separator)

    return lines


def _format_callout(block: doc_models.CalloutBlock) -> list[str]:
    directive_map = {
        "info": "note",
        "warning": "warning",
        "error": "danger",
        "success": "tip",
    }
    directive = directive_map.get(block.variant, "note")
    lines = [f".. {directive}::", ""]
    for line in block.text.split("\n"):
        lines.append(f"   {line}")
    return lines


def _format_mermaid(
    block: doc_models.MermaidBlock,
    mermaid_image_paths: dict[str, str] | None,
) -> list[str]:
    if mermaid_image_paths and block.diagram in mermaid_image_paths:
        rel = mermaid_image_paths[block.diagram]
        return [
            f".. image:: {rel}",
            "   :alt: Mermaid diagram",
        ]
    lines = [".. mermaid::", ""]
    for line in block.diagram.split("\n"):
        lines.append(f"   {line}")
    return lines


def _format_cut(
    block: doc_models.CutBlock,
    mermaid_image_paths: dict[str, str] | None,
) -> list[str]:
    lines = [
        ".. dropdown:: " + block.title,
        f"   :open: {'true' if block.default_open else 'false'}",
        "",
    ]
    for nested_block in block.blocks:
        nested_lines = format_block(nested_block, mermaid_image_paths)
        for line in nested_lines:
            lines.append(f"   {line}")
        lines.append("")
    return lines


def _format_image(block: doc_models.ImageBlock) -> list[str]:
    lines = [f".. image:: {block.src}", f"   :alt: {block.alt}"]
    if block.caption:
        lines.append("")
        lines.append(f"   {block.caption}")
    return lines
