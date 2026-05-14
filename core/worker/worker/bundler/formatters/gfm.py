from pathlib import Path
import typing as tp

from source2doc.formatter.mdx import blocks as mdx_blocks
from source2doc.logging import get_logger
from source2doc.models import docs as doc_models

from worker.bundler import mermaid as mermaid_render
from worker.bundler.formatters import env as formatter_env


logger = get_logger(__name__)


async def format_bundle(
    env: formatter_env.GFMFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
    mermaid_render_mode: mermaid_render.MermaidRenderMode = "fence",
) -> None:
    """Write generated pages as a plain GitHub-Flavored Markdown bundle.

    Output layout::

        <output_dir>/
            README.md            # project index with nested bullet list
            <group_slug>/
                README.md        # group landing page
                <page>.md        # group children
            <page>.md            # top-level pages

    The format is portable: any plain Markdown viewer (github.com, GitLab,
    Bitbucket, VS Code preview) renders it without extra config files. Mermaid
    fences are kept as ``mermaid`` code blocks since GitHub renders them
    natively.
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    mermaid_paths = await mermaid_render.prerender_mermaid_for_pages(
        pages, output_dir, mermaid_render_mode
    )

    groups = _collect_groups(index.navigation)
    extension = env.get_file_extension()
    page_ids = set(pages.keys())
    group_slugs = set(groups.values())

    for page_id, page in pages.items():
        if page_id in groups:
            group_slug = groups[page_id]
            page_path = output_dir / group_slug / f"{page_id}{extension}"
            mermaid_paths_rel = _rewrite_relative_to(mermaid_paths, depth=1)
        else:
            page_path = _page_id_to_path(output_dir, page_id, extension)
            depth = max(0, len(page_path.relative_to(output_dir).parts) - 1)
            mermaid_paths_rel = _rewrite_relative_to(mermaid_paths, depth=depth)
        page_path.parent.mkdir(parents=True, exist_ok=True)
        content = _format_page(page, mermaid_paths_rel, page_ids, group_slugs)
        page_path.write_text(content, encoding="utf-8")

    _generate_group_readmes(output_dir, index.navigation, pages, extension)
    _generate_root_readme(output_dir, index, pages)
    _generate_sidebar(output_dir, index.navigation, pages)
    _generate_index_html(output_dir)


async def generate_config(
    env: formatter_env.GFMFormatterEnv,
    output_dir: Path,
    config_data: dict[str, tp.Any],
) -> None:
    """GFM bundles need no config — kept for protocol symmetry."""
    return None


async def generate_dockerfile(
    env: formatter_env.GFMFormatterEnv,
    output_dir: Path,
) -> None:
    """Ship a docsify-based serve image so the bundle self-serves.

    docsify renders ``*.md`` in-browser from a single ``index.html``,
    auto-discovers ``README.md`` as the index, and follows our existing
    folder-of-md layout without rewrites.
    """

    dockerfile = (
        "FROM node:20-alpine\n"
        "RUN npm install -g docsify-cli@4\n"
        "WORKDIR /docs\n"
        "COPY . /docs\n"
        "EXPOSE 3000\n"
        'CMD ["docsify", "serve", "/docs", "--port", "3000"]\n'
    )
    (output_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")


def _collect_groups(navigation: dict[str, str | dict]) -> dict[str, str]:
    """Return a mapping of child page_id -> group_slug for navigation groups."""
    result: dict[str, str] = {}
    for slug, data in navigation.items():
        if isinstance(data, dict) and "children" in data:
            for child_id in data["children"]:
                result[child_id] = slug
    return result


def _page_id_to_path(output_dir: Path, page_id: str, extension: str) -> Path:
    parts = [p for p in page_id.split("/") if p and p not in (".", "..")]
    rel = Path(*parts).with_suffix(extension)
    return output_dir / rel


def _rewrite_relative_to(
    mermaid_paths: dict[str, str],
    depth: int,
) -> dict[str, str]:
    """Rewrite mermaid image paths so they are relative to a page at ``depth``.

    ``depth`` is the number of directory levels between the page and the
    bundle root. ``depth == 0`` means the page sits at the root.
    """
    if not mermaid_paths or depth == 0:
        return mermaid_paths
    prefix = "../" * depth
    # Drop the leading "./" (added by the formatter) — mermaid_paths are
    # already root-relative; we want "<../>*<root_relative>".
    return {diagram: f"{prefix}{rel}" for diagram, rel in mermaid_paths.items()}


def _format_page(
    page: doc_models.DocPage,
    mermaid_image_paths: dict[str, str] | None,
    page_ids: set[str],
    group_slugs: set[str],
) -> str:
    lines: list[str] = []

    lines.append(f"# {page.title}")
    lines.append("")
    if page.summary:
        lines.append(page.summary)
        lines.append("")

    for block in page.blocks:
        lines.extend(mdx_blocks.format_block(block, mermaid_image_paths))
        lines.append("")

    related = [rid for rid in page.related if rid in page_ids or rid in group_slugs]
    if related:
        lines.append("## Related Pages")
        lines.append("")
        for related_id in related:
            lines.append(f"- [{related_id}](./{related_id}.md)")
        lines.append("")

    return "\n".join(lines)


def _generate_group_readmes(
    output_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    extension: str,
) -> None:
    """Emit a ``README.md`` inside each group directory listing its children.

    GitHub auto-renders ``README.md`` when navigating into a folder, so this
    gives each group a usable landing page without a synthetic ``index`` page.
    """
    for slug, data in navigation.items():
        if not (isinstance(data, dict) and "children" in data):
            continue

        group_dir = output_dir / slug
        group_dir.mkdir(parents=True, exist_ok=True)

        readme_path = group_dir / "README.md"
        if readme_path.exists():
            continue

        title = str(data.get("title", slug.replace("-", " ").replace("_", " ").title()))
        children: dict[str, str | dict] = data["children"]

        lines: list[str] = [f"# {title}", ""]
        if children:
            lines.append("## Pages")
            lines.append("")
            for child_id, child_data in children.items():
                child_title = _resolve_title(child_id, child_data, pages)
                lines.append(f"- [{child_title}](./{child_id}{extension})")
            lines.append("")

        readme_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("gfm_group_readme_created", group=slug, path=str(readme_path))


def _generate_root_readme(
    output_dir: Path,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
) -> None:
    """Generate top-level ``README.md`` with a nested bullet list of all pages."""
    readme_path = output_dir / "README.md"

    lines: list[str] = ["# Documentation", ""]
    lines.append("Generated by source2doc bundler.")
    lines.append("")

    if index.navigation:
        lines.append("## Contents")
        lines.append("")
        lines.extend(_render_navigation(index.navigation, pages, prefix="."))
        lines.append("")

    readme_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("gfm_root_readme_created", path=str(readme_path))


def _render_navigation(
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    prefix: str,
    depth: int = 0,
) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    for nav_id, nav_data in navigation.items():
        if isinstance(nav_data, dict) and "children" in nav_data:
            group_title = str(
                nav_data.get("title", nav_id.replace("-", " ").replace("_", " ").title())
            )
            lines.append(f"{indent}- [{group_title}]({prefix}/{nav_id}/README.md)")
            children: dict[str, str | dict] = nav_data["children"]
            child_indent = "  " * (depth + 1)
            for child_id, child_data in children.items():
                child_title = _resolve_title(child_id, child_data, pages)
                lines.append(f"{child_indent}- [{child_title}]({prefix}/{nav_id}/{child_id}.md)")
        else:
            title = _resolve_title(nav_id, nav_data, pages)
            lines.append(f"{indent}- [{title}]({prefix}/{nav_id}.md)")
    return lines


def _resolve_title(
    page_id: str,
    nav_data: str | dict,
    pages: dict[str, doc_models.DocPage],
) -> str:
    if page_id in pages and pages[page_id].title:
        return pages[page_id].title
    if isinstance(nav_data, dict):
        return str(nav_data.get("title", page_id))
    return str(nav_data)


def _generate_sidebar(
    output_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
) -> None:
    """Emit ``_sidebar.md`` consumed by docsify's persistent left nav."""
    lines = _render_navigation(navigation, pages, prefix=".")
    (output_dir / "_sidebar.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("gfm_sidebar_created", path=str(output_dir / "_sidebar.md"))


def _generate_index_html(output_dir: Path) -> None:
    """Drop a minimal docsify entrypoint so the Dockerfile can serve it."""

    index_html = (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\">\n"
        "  <title>Documentation</title>\n"
        "  <meta name=\"viewport\" "
        "content=\"width=device-width, initial-scale=1.0, minimum-scale=1.0\">\n"
        "  <meta name=\"description\" content=\"Documentation generated by source2doc\">\n"
        "  <link rel=\"stylesheet\" "
        "href=\"https://cdn.jsdelivr.net/npm/docsify@4/lib/themes/vue.css\">\n"
        "</head>\n"
        "<body>\n"
        "  <div id=\"app\">Loading...</div>\n"
        "  <script>\n"
        "    window.$docsify = {\n"
        "      name: 'Documentation',\n"
        "      loadSidebar: true,\n"
        "      subMaxLevel: 3,\n"
        "      auto2top: true,\n"
        "      relativePath: true,\n"
        "      alias: { '/.*/_sidebar.md': '/_sidebar.md' },\n"
        "      search: 'auto'\n"
        "    };\n"
        "  </script>\n"
        "  <script src=\"https://cdn.jsdelivr.net/npm/docsify@4\"></script>\n"
        "  <script "
        "src=\"https://cdn.jsdelivr.net/npm/docsify/lib/plugins/search.min.js\"></script>\n"
        "</body>\n"
        "</html>\n"
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
