from source2doc.models import docs as doc_models


def format_block(
    block: doc_models.DocBlock,
    mermaid_image_paths: dict[str, str] | None = None,
) -> list[str]:
    """Render a single :class:`DocBlock` into Markdown/MDX lines.

    ``mermaid_image_paths`` (optional) maps a Mermaid diagram body to a
    bundle-relative image path. When a mermaid block's diagram text is in
    the map, the fence is replaced with an ``![](./<rel_path>)`` image
    reference. Otherwise the original ```` ```mermaid ```` fence is emitted.
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
    return [f"{'#' * block.level} {block.text}"]


def _format_paragraph(block: doc_models.ParagraphBlock) -> list[str]:
    return [block.text]


def _format_code(block: doc_models.CodeBlock) -> list[str]:
    return [
        f"```{block.lang}",
        block.code,
        "```",
    ]


def _format_list(block: doc_models.ListBlock) -> list[str]:
    lines = []
    for idx, item in enumerate(block.items):
        prefix = f"{idx + 1}." if block.ordered else "-"
        lines.append(f"{prefix} {item.text}")
    return lines


def _format_table(block: doc_models.TableBlock) -> list[str]:
    lines = []
    lines.append("| " + " | ".join(block.headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(block.headers)) + " |")
    for row in block.rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _format_callout(block: doc_models.CalloutBlock) -> list[str]:
    variant_map = {
        "info": "💡",
        "warning": "⚠️",
        "error": "❌",
        "success": "✅",
    }
    icon = variant_map.get(block.variant, "ℹ️")
    return [
        f"> {icon} **{block.variant.upper()}**",
        f"> {block.text}",
    ]


def _format_mermaid(
    block: doc_models.MermaidBlock,
    mermaid_image_paths: dict[str, str] | None,
) -> list[str]:
    if mermaid_image_paths and block.diagram in mermaid_image_paths:
        rel = mermaid_image_paths[block.diagram]
        # Path is already page-relative; prefix "./" for top-level pages so
        # the link is unambiguously relative.
        href = rel if rel.startswith(("./", "../")) else f"./{rel}"
        return [f"![Mermaid diagram]({href})"]
    return [
        "```mermaid",
        block.diagram,
        "```",
    ]


def _format_cut(
    block: doc_models.CutBlock,
    mermaid_image_paths: dict[str, str] | None,
) -> list[str]:
    lines = [
        f"<details{' open' if block.default_open else ''}>",
        f"<summary>{block.title}</summary>",
        "",
    ]
    for nested_block in block.blocks:
        lines.extend(format_block(nested_block, mermaid_image_paths))
        lines.append("")
    lines.append("</details>")
    return lines


def _format_image(block: doc_models.ImageBlock) -> list[str]:
    alt_text = block.alt or ""
    caption = f"\n*{block.caption}*" if block.caption else ""
    return [f"![{alt_text}]({block.src}){caption}"]
