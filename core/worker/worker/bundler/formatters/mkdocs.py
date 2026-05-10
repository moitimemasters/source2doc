from pathlib import Path
import typing as tp

from source2doc.formatter.mdx import blocks as mdx_blocks
from source2doc.models import docs as doc_models

from worker.bundler import mermaid as mermaid_render
from worker.bundler import templates
from worker.bundler.formatters import env as formatter_env


async def format_bundle(
    env: formatter_env.MkDocsFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
    mermaid_render_mode: mermaid_render.MermaidRenderMode = "fence",
) -> None:
    docs_dir = output_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # MkDocs has a JS-side mermaid extension by default — keep fences unless
    # the operator explicitly asks for static images.
    mermaid_paths = await mermaid_render.prerender_mermaid_for_pages(
        pages, docs_dir, mermaid_render_mode
    )

    for page_id, page in pages.items():
        content = _format_page(page, mermaid_paths)
        page_path = docs_dir / f"{page_id}{env.get_file_extension()}"
        page_path.write_text(content, encoding="utf-8")


async def generate_config(
    env: formatter_env.MkDocsFormatterEnv,
    output_dir: Path,
    config_data: dict[str, tp.Any],
) -> None:
    navigation = _build_navigation(config_data.get("navigation", {}))

    mkdocs_config = templates.render_template(
        "mkdocs",
        "config",
        "mkdocs.yml.j2",
        {
            "site_name": config_data.get("site_name", "Documentation"),
            "site_description": config_data.get("site_description", "Generated documentation"),
            "site_author": config_data.get("site_author", "source2doc"),
            "navigation": navigation,
        },
    )

    config_path = output_dir / "mkdocs.yml"
    config_path.write_text(mkdocs_config, encoding="utf-8")

    requirements = templates.load_template_file("mkdocs", "config", "requirements.txt")
    requirements_path = output_dir / "requirements.txt"
    requirements_path.write_text(requirements, encoding="utf-8")


async def generate_dockerfile(
    env: formatter_env.MkDocsFormatterEnv,
    output_dir: Path,
) -> None:
    dockerfile = templates.load_template_file("mkdocs", "docker", "Dockerfile")
    dockerfile_path = output_dir / "Dockerfile"
    dockerfile_path.write_text(dockerfile, encoding="utf-8")


def _format_page(
    page: doc_models.DocPage,
    mermaid_image_paths: dict[str, str] | None = None,
) -> str:
    lines = []

    lines.append(f"# {page.title}")
    lines.append("")
    lines.append(page.summary)
    lines.append("")

    for block in page.blocks:
        lines.extend(mdx_blocks.format_block(block, mermaid_image_paths))
        lines.append("")

    if page.related:
        lines.append("## Related Pages")
        lines.append("")
        for related_id in page.related:
            lines.append(f"- [{related_id}](./{related_id}.md)")
        lines.append("")

    return "\n".join(lines)


def _build_navigation(navigation: dict) -> list[dict[str, str]]:
    nav_items = []
    for page_id, page_data in navigation.items():
        title = page_data.get("title", page_id) if isinstance(page_data, dict) else page_id

        nav_items.append(
            {
                "title": title,
                "path": f"docs/{page_id}.md",
            }
        )
    return nav_items
