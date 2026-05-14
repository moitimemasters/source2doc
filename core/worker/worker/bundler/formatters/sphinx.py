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

    # Always ensure the mermaid/ directory exists so the Dockerfile's
    # ``COPY mermaid ./mermaid`` step never fails on empty bundles.
    (output_dir / "mermaid").mkdir(parents=True, exist_ok=True)

    page_ids = set(pages.keys())
    extension = env.get_file_extension()

    for page_id, page in pages.items():
        content = _format_page(page, mermaid_paths, page_ids)
        page_path = output_dir / f"{page_id}{extension}"
        page_path.write_text(content, encoding="utf-8")

    _generate_index_rst(output_dir, index.navigation, pages)


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
    mermaid_image_paths: dict[str, str] | None,
    page_ids: set[str],
) -> str:
    lines: list[str] = []

    title_underline = "=" * max(1, len(page.title))
    lines.append(title_underline)
    lines.append(page.title)
    lines.append(title_underline)
    lines.append("")

    if page.summary:
        lines.append(page.summary)
        lines.append("")

    for block in page.blocks:
        lines.extend(rst_blocks.format_block(block, mermaid_image_paths))
        lines.append("")

    bullets = [f"* :doc:`{rid}`" for rid in page.related if rid in page_ids]
    if bullets:
        lines.append("Related Pages")
        lines.append("-" * len("Related Pages"))
        lines.append("")
        lines.extend(bullets)
        lines.append("")

    return "\n".join(lines)


def _generate_index_rst(
    output_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
) -> None:
    """Emit root ``index.rst`` plus a section-index ``{group}.rst`` per group.

    Files stay flat in the bundle root (named after their original
    ``page_id``). The root toctree references group ids; each group file
    toctrees its real children. ``sphinx-rtd-theme`` then renders a nested
    sidebar without us moving files around.
    """

    page_set = set(pages.keys())
    root_entries: list[str] = []

    for nav_id, data in navigation.items():
        if nav_id == "index":
            continue

        if isinstance(data, dict) and "children" in data:
            children = [cid for cid in data["children"] if cid in page_set]
            if not children:
                continue
            section_doc = _section_docname(nav_id, page_set)
            _write_section_index(
                output_dir=output_dir,
                section_doc=section_doc,
                title=str(data.get("title", _humanise(nav_id))),
                children=children,
            )
            root_entries.append(section_doc)
        else:
            if nav_id not in page_set:
                continue
            root_entries.append(nav_id)

    lines: list[str] = [
        "Documentation",
        "=" * len("Documentation"),
        "",
        ".. toctree::",
        "   :maxdepth: 2",
        "   :caption: Contents:",
        "",
    ]
    for entry in root_entries:
        lines.append(f"   {entry}")
    lines.append("")

    (output_dir / "index.rst").write_text("\n".join(lines), encoding="utf-8")


def _section_docname(group_slug: str, page_set: set[str]) -> str:
    """Return a docname for a group's section index, avoiding collisions.

    If the group slug already names a real leaf page, prefix to keep both.
    """
    if group_slug in page_set:
        return f"_section_{group_slug}"
    return group_slug


def _write_section_index(
    *,
    output_dir: Path,
    section_doc: str,
    title: str,
    children: list[str],
) -> None:
    bar = "=" * max(1, len(title))
    lines: list[str] = [
        bar,
        title,
        bar,
        "",
        ".. toctree::",
        "   :maxdepth: 2",
        "",
    ]
    for child_id in children:
        lines.append(f"   {child_id}")
    lines.append("")
    (output_dir / f"{section_doc}.rst").write_text("\n".join(lines), encoding="utf-8")


def _humanise(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()
