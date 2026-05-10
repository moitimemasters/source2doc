import json
from pathlib import Path

from source2doc.formatter.mdx import blocks
from source2doc.formatter.mdx.env import MDXFormatterEnv
from source2doc.models import docs as doc_models


async def format_bundle(
    env: MDXFormatterEnv,
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


def _format_page(page: doc_models.DocPage) -> str:
    lines = []

    lines.append("---")
    lines.append(f"title: {page.title}")
    lines.append(f"description: {page.summary}")
    if page.metadata.tags:
        tags_str = ", ".join(page.metadata.tags)
        lines.append(f"tags: [{tags_str}]")
    lines.append("---")
    lines.append("")

    lines.append(f"# {page.title}")
    lines.append("")
    lines.append(page.summary)
    lines.append("")

    for block in page.blocks:
        lines.extend(blocks.format_block(block))
        lines.append("")

    if page.related:
        lines.append("## Related Pages")
        lines.append("")
        for related_id in page.related:
            lines.append(f"- [{related_id}](./{related_id})")
        lines.append("")

    return "\n".join(lines)


def _format_navigation(navigation: dict) -> str:
    return json.dumps(navigation, indent=2, ensure_ascii=False)
