from pathlib import Path
import typing as tp

from source2doc.formatter.rst import blocks as rst_blocks
from source2doc.models import docs as doc_models

from worker.bundler import mermaid as mermaid_render
from worker.bundler import templates
from worker.bundler.formatters import env as formatter_env


async def format_bundle(
    env: formatter_env.SphinxFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
    mermaid_render_mode: mermaid_render.MermaidRenderMode = "fence",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    mermaid_paths = await mermaid_render.prerender_mermaid_for_pages(
        pages, output_dir, mermaid_render_mode
    )

    for page_id, page in pages.items():
        content = _format_page(page, mermaid_paths)
        page_path = output_dir / f"{page_id}{env.get_file_extension()}"
        page_path.write_text(content, encoding="utf-8")

    _generate_index_rst(output_dir, index.navigation)


async def generate_config(
    env: formatter_env.SphinxFormatterEnv,
    output_dir: Path,
    config_data: dict[str, tp.Any],
) -> None:
    conf_py = templates.render_template(
        "sphinx",
        "config",
        "conf.py.j2",
        {
            "project_name": config_data.get("project_name", "Documentation"),
            "copyright": config_data.get("copyright", "2024"),
            "author": config_data.get("author", "source2doc"),
            "release": config_data.get("release", "1.0.0"),
        },
    )

    conf_path = output_dir / "conf.py"
    conf_path.write_text(conf_py, encoding="utf-8")

    requirements = templates.load_template_file("sphinx", "config", "requirements.txt")
    requirements_path = output_dir / "requirements.txt"
    requirements_path.write_text(requirements, encoding="utf-8")


async def generate_dockerfile(
    env: formatter_env.SphinxFormatterEnv,
    output_dir: Path,
) -> None:
    dockerfile = templates.load_template_file("sphinx", "docker", "Dockerfile")
    dockerfile_path = output_dir / "Dockerfile"
    dockerfile_path.write_text(dockerfile, encoding="utf-8")


def _format_page(
    page: doc_models.DocPage,
    mermaid_image_paths: dict[str, str] | None = None,
) -> str:
    lines = []

    title_underline = "=" * len(page.title)
    lines.append(title_underline)
    lines.append(page.title)
    lines.append(title_underline)
    lines.append("")

    lines.append(page.summary)
    lines.append("")

    for block in page.blocks:
        lines.extend(rst_blocks.format_block(block, mermaid_image_paths))
        lines.append("")

    if page.related:
        lines.append("Related Pages")
        lines.append("-" * len("Related Pages"))
        lines.append("")
        for related_id in page.related:
            lines.append(f"* :doc:`{related_id}`")
        lines.append("")

    return "\n".join(lines)


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
