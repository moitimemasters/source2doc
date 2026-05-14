from pathlib import Path
import typing as tp

import yaml

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

    page_ids = set(pages.keys())
    extension = env.get_file_extension()

    for page_id, page in pages.items():
        content = _format_page(page, mermaid_paths, page_ids)
        page_path = docs_dir / f"{page_id}{extension}"
        page_path.write_text(content, encoding="utf-8")

    _ensure_index_page(docs_dir, index.navigation, pages, extension)


async def generate_config(
    env: formatter_env.MkDocsFormatterEnv,
    output_dir: Path,
    config_data: dict[str, tp.Any],
) -> None:
    nav_yaml = _build_navigation_yaml(
        config_data.get("navigation", {}),
        config_data.get("pages") or {},
    )

    mkdocs_config = templates.render_template(
        "mkdocs",
        "config",
        "mkdocs.yml.j2",
        {
            "site_name": config_data.get("site_name", "Documentation"),
            "site_description": config_data.get("site_description", "Generated documentation"),
            "site_author": config_data.get("site_author", "source2doc"),
            "navigation_yaml": nav_yaml,
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
    mermaid_image_paths: dict[str, str] | None,
    page_ids: set[str],
) -> str:
    lines = []

    lines.append(f"# {page.title}")
    lines.append("")
    if page.summary:
        lines.append(page.summary)
        lines.append("")

    for block in page.blocks:
        lines.extend(mdx_blocks.format_block(block, mermaid_image_paths))
        lines.append("")

    bullets = []
    for related_id in page.related:
        if related_id in page_ids:
            bullets.append(f"- [{related_id}]({related_id}.md)")
    if bullets:
        lines.append("## Related Pages")
        lines.append("")
        lines.extend(bullets)
        lines.append("")

    return "\n".join(lines)


def _resolve_title(
    page_id: str,
    nav_data: str | dict | None,
    pages: dict[str, doc_models.DocPage],
) -> str:
    if page_id in pages and pages[page_id].title:
        return pages[page_id].title
    if isinstance(nav_data, dict):
        return str(nav_data.get("title", page_id))
    if isinstance(nav_data, str) and nav_data:
        return nav_data
    return page_id.replace("-", " ").replace("_", " ").title()


def _build_navigation_yaml(
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
) -> str:
    """Produce the YAML body for the ``nav:`` key.

    Files are flat under ``docs/`` (named ``{page_id}.md``). MkDocs renders
    nested ``nav:`` groups in the sidebar without affecting URLs, so we emit
    a hierarchical list using only filenames — never a ``docs/`` prefix.
    """

    nav: list[dict] = [{"Home": "index.md"}]
    page_set = set(pages.keys())

    for nav_id, data in navigation.items():
        if nav_id == "index":
            continue

        if isinstance(data, dict) and "children" in data:
            group_title = str(data.get("title", _humanise(nav_id)))
            child_entries: list[dict] = []
            for child_id, child_data in data["children"].items():
                if child_id not in page_set:
                    continue
                child_title = _resolve_title(child_id, child_data, pages)
                child_entries.append({child_title: f"{child_id}.md"})
            if child_entries:
                nav.append({group_title: child_entries})
        else:
            if nav_id not in page_set:
                continue
            title = _resolve_title(nav_id, data, pages)
            nav.append({title: f"{nav_id}.md"})

    return yaml.safe_dump(nav, sort_keys=False, allow_unicode=True, width=10_000)


def _ensure_index_page(
    docs_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    extension: str,
) -> None:
    """Synthesise ``docs/index.md`` if no real one was generated.

    Without an index page MkDocs has no homepage and ``/`` 404s.
    Links from the synthesised index reference the *real* flat filenames
    (matching what we put in ``nav:``).
    """

    index_path = docs_dir / f"index{extension}"
    if index_path.exists():
        return

    lines: list[str] = ["# Documentation", "", "Generated by source2doc bundler.", ""]
    if navigation:
        lines.append("## Contents")
        lines.append("")
        for nav_id, data in navigation.items():
            if nav_id == "index":
                continue
            if isinstance(data, dict) and "children" in data:
                group_title = str(data.get("title", _humanise(nav_id)))
                lines.append(f"- **{group_title}**")
                for child_id, child_data in data["children"].items():
                    if child_id not in pages:
                        continue
                    child_title = _resolve_title(child_id, child_data, pages)
                    lines.append(f"    - [{child_title}]({child_id}{extension})")
            else:
                if nav_id not in pages:
                    continue
                title = _resolve_title(nav_id, data, pages)
                lines.append(f"- [{title}]({nav_id}{extension})")
        lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")


def _humanise(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()
