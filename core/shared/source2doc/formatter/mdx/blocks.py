import re

from source2doc.models import docs as doc_models


# Strip Sphinx / MyST cross-reference roles like ``{class}`Command` `` or
# ``{func}`run` `` — MDX 3 parses ``{...}`` as a JSX expression and the
# role names become bare identifiers (``class`` is a reserved word) and
# raise SyntaxError. Drop the role prefix and keep the inline-code span.
_SPHINX_ROLE_RE = re.compile(
    r"\{(?:class|func|meth|attr|mod|data|exc|obj|const|ref|doc|py:[\w.]+|code)\}(`[^`]+`)"
)


def escape_mdx_text(text: str) -> str:
    """Make a raw text run safe for inline MDX.

    Two transformations:

    1. Drop Sphinx/MyST inline role prefixes (e.g. ``{class}\\`X\\``` → ``\\`X\\```).
       Writers trained on Python docs sometimes leak these into prose.
    2. Escape stray ``{`` / ``}`` outside inline code spans so MDX 3 stops
       treating them as JSX expression boundaries (`Could not parse
       expression with acorn` build errors).

    Code blocks are protected by the caller — fenced/inline code is left
    untouched. This helper only runs on free-form text from
    paragraphs, headings, list items, callouts, and table cells.
    """
    if not text:
        return text

    text = _SPHINX_ROLE_RE.sub(r"\1", text)

    # Walk the string, skipping inline code spans (``…``). Escape braces
    # only in the non-code segments.
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "`":
            # Find matching closing backtick(s) of the same run length.
            run = 1
            while i + run < n and text[i + run] == "`":
                run += 1
            close = text.find("`" * run, i + run)
            if close == -1:
                # Unterminated span; treat the rest as plain text but still
                # don't escape the leading backticks themselves.
                out.append(text[i : i + run])
                i += run
                continue
            out.append(text[i : close + run])
            i = close + run
            continue
        if ch in "{}":
            out.append("\\" + ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


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
    return [f"{'#' * block.level} {escape_mdx_text(block.text)}"]


def _format_paragraph(block: doc_models.ParagraphBlock) -> list[str]:
    return [escape_mdx_text(block.text)]


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
        lines.append(f"{prefix} {escape_mdx_text(item.text)}")
    return lines


def _format_table(block: doc_models.TableBlock) -> list[str]:
    lines = []
    lines.append("| " + " | ".join(escape_mdx_text(h) for h in block.headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(block.headers)) + " |")
    for row in block.rows:
        lines.append("| " + " | ".join(escape_mdx_text(c) for c in row) + " |")
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
        f"> {escape_mdx_text(block.text)}",
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
        f"<summary>{escape_mdx_text(block.title)}</summary>",
        "",
    ]
    for nested_block in block.blocks:
        lines.extend(format_block(nested_block, mermaid_image_paths))
        lines.append("")
    lines.append("</details>")
    return lines


def _format_image(block: doc_models.ImageBlock) -> list[str]:
    alt_text = escape_mdx_text(block.alt or "")
    caption = f"\n*{escape_mdx_text(block.caption)}*" if block.caption else ""
    return [f"![{alt_text}]({block.src}){caption}"]
