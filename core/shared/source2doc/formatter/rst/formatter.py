import json
from pathlib import Path

from source2doc.formatter.rst import blocks
from source2doc.formatter.rst.env import RSTFormatterEnv
from source2doc.models import docs as doc_models


async def format_bundle(
    env: RSTFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for page_id, page in pages.items():
        content = _format_page(page)
        page_path = output_dir / f"{page_id}{env.get_file_extension()}"
        page_path.write_text(content, encoding="utf-8")

    nav_content = _format_navigation(index.navigation)
    nav_path = output_dir / "navigation.json"
    nav_path.write_text(nav_content, encoding="utf-8")

    _generate_index_rst(output_dir, index.navigation)


def _format_page(page: doc_models.DocPage) -> str:
    lines = []

    title_underline = "=" * len(page.title)
    lines.append(title_underline)
    lines.append(page.title)
    lines.append(title_underline)
    lines.append("")

    lines.append(page.summary)
    lines.append("")

    for block in page.blocks:
        lines.extend(blocks.format_block(block))
        lines.append("")

    if page.related:
        lines.append("Related Pages")
        lines.append("-" * len("Related Pages"))
        lines.append("")
        for related_id in page.related:
            lines.append(f"* :doc:`{related_id}`")
        lines.append("")

    return "\n".join(lines)


def _format_navigation(navigation: dict) -> str:
    return json.dumps(navigation, indent=2, ensure_ascii=False)


def _generate_index_rst(output_dir: Path, navigation: dict) -> None:
    lines = [
        "Documentation",
        "=" * len("Documentation"),
        "",
        ".. toctree::",
        "   :maxdepth: 2",
        "   :caption: Contents:",
        "",
    ]

    for page_id in navigation:
        lines.append(f"   {page_id}")

    lines.append("")

    index_path = output_dir / "index.rst"
    index_path.write_text("\n".join(lines), encoding="utf-8")
