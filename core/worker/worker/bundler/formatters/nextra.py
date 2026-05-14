import json
from pathlib import Path
import typing as tp

import yaml

from source2doc.formatter.mdx import blocks as mdx_blocks
from source2doc.logging import get_logger
from source2doc.models import docs as doc_models

from worker.bundler import mermaid as mermaid_render
from worker.bundler import templates
from worker.bundler.formatters import env as formatter_env


logger = get_logger(__name__)


async def format_bundle(
    env: formatter_env.NextraFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
    mermaid_render_mode: mermaid_render.MermaidRenderMode = "fence",
) -> None:
    """Write generated pages into a Nextra v4-compatible structure.

    Nextra v4 docs theme (App Router) can render MDX from the `content/` directory.
    See: https://nextra.site/docs/docs-theme/start

    We intentionally do NOT use the legacy `pages/` directory.
    """

    content_dir = output_dir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)

    # Nextra has a JS-side mermaid renderer in the docs theme — keep fences
    # by default. ``mermaid_render_mode != "fence"`` opts in to static images.
    mermaid_paths = await mermaid_render.prerender_mermaid_for_pages(
        pages, content_dir, mermaid_render_mode
    )

    # Collect group sections (navigation entries with "children") so we know
    # which page_ids belong to a group and should be nested under a subdirectory.
    groups = _collect_groups(index.navigation)

    page_ids = set(pages.keys())

    for page_id, page in pages.items():
        # If this page_id belongs to a group, place it inside the group subdirectory.
        if page_id in groups:
            group_slug = groups[page_id]
            page_path = content_dir / group_slug / f"{page_id}{env.get_file_extension()}"
            page_mermaid_paths = _rewrite_mermaid_paths(mermaid_paths, depth=1)
        else:
            page_path = _page_id_to_content_path(content_dir, page_id, env.get_file_extension())
            depth = max(0, len(page_path.relative_to(content_dir).parts) - 1)
            page_mermaid_paths = _rewrite_mermaid_paths(mermaid_paths, depth=depth)
        page_path.parent.mkdir(parents=True, exist_ok=True)
        content = _format_page(page, page_mermaid_paths, page_ids, groups)
        page_path.write_text(content, encoding="utf-8")

    _ensure_index_page(content_dir, index.navigation, pages, groups)
    _generate_group_index_pages(content_dir, index.navigation, pages, env.get_file_extension())
    _generate_meta_files(content_dir, index.navigation, pages, groups)


async def generate_config(
    env: formatter_env.NextraFormatterEnv,
    output_dir: Path,
    config_data: dict[str, tp.Any],
) -> None:
    """Generate Next.js/Nextra config files.

    The official Nextra v4 setup uses:
    - `next.config.mjs` with `nextra()` and turbopack alias for mdx-components
    - `mdx-components.*` file
    - `app/layout.*` + `app/[[...mdxPath]]/page.*` for App Router integration
    """

    package_json = templates.render_template(
        "nextra",
        "config",
        "package.json.j2",
        {
            "project_name": config_data.get("project_name", "documentation"),
        },
    )

    package_path = output_dir / "package.json"
    package_path.write_text(package_json, encoding="utf-8")

    next_config = templates.load_template_file("nextra", "config", "next.config.mjs")
    next_config_path = output_dir / "next.config.mjs"
    next_config_path.write_text(next_config, encoding="utf-8")

    mdx_components = templates.load_template_file("nextra", "config", "mdx-components.js")
    mdx_components_path = output_dir / "mdx-components.js"
    mdx_components_path.write_text(mdx_components, encoding="utf-8")

    layout = templates.load_template_file("nextra", "config", "app.layout.jsx")
    layout_path = output_dir / "app" / "layout.jsx"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(layout, encoding="utf-8")

    mdx_page = templates.load_template_file(
        "nextra",
        "config",
        "app.[[...mdxPath]].page.jsx",
    )
    mdx_page_path = output_dir / "app" / "[[...mdxPath]]" / "page.jsx"
    mdx_page_path.parent.mkdir(parents=True, exist_ok=True)
    mdx_page_path.write_text(mdx_page, encoding="utf-8")


async def generate_dockerfile(
    env: formatter_env.NextraFormatterEnv,
    output_dir: Path,
) -> None:
    dockerfile = templates.load_template_file("nextra", "docker", "Dockerfile")
    dockerfile_path = output_dir / "Dockerfile"
    dockerfile_path.write_text(dockerfile, encoding="utf-8")


def _collect_groups(navigation: dict[str, str | dict]) -> dict[str, str]:
    """Return a mapping of child page_id -> group_slug for all navigation groups.

    A "group" is a navigation entry whose value is a dict with a ``children`` key.
    The children are flat page_ids that should be placed inside a subdirectory
    named after the group slug.

    Example::

        navigation = {
            "bot-commands": {
                "title": "Bot Commands",
                "children": {
                    "find-command": "Find Command",
                    "stop-command": "Stop Command",
                }
            }
        }
        # returns {"find-command": "bot-commands", "stop-command": "bot-commands"}
    """
    result: dict[str, str] = {}
    for slug, data in navigation.items():
        if isinstance(data, dict) and "children" in data:
            for child_id in data["children"]:
                result[child_id] = slug
    return result


def _page_id_to_content_path(content_dir: Path, page_id: str, extension: str) -> Path:
    # Normalize `page_id` to a safe relative path, supporting nested pages.
    parts = [p for p in page_id.split("/") if p and p not in (".", "..")]
    rel = Path(*parts).with_suffix(extension)
    return content_dir / rel


def _rewrite_mermaid_paths(
    mermaid_paths: dict[str, str],
    depth: int,
) -> dict[str, str]:
    if not mermaid_paths or depth == 0:
        return mermaid_paths
    prefix = "../" * depth
    return {diagram: f"{prefix}{rel}" for diagram, rel in mermaid_paths.items()}


def _yaml_frontmatter(fields: dict[str, object]) -> str:
    """Emit a YAML frontmatter block with safe quoting.

    Raw f-string emission used to break MDX whenever a title/description
    contained a colon, ``#``, leading whitespace, etc. ``yaml.safe_dump``
    picks an appropriate quoting style automatically.
    """
    body = yaml.safe_dump(
        fields,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    ).rstrip("\n")
    return "---\n" + body + "\n---\n"


def _format_page(
    page: doc_models.DocPage,
    mermaid_image_paths: dict[str, str] | None,
    page_ids: set[str],
    groups: dict[str, str],
) -> str:
    fm: dict[str, object] = {"title": page.title}
    if page.summary:
        fm["description"] = page.summary
    if page.metadata.tags:
        fm["tags"] = list(page.metadata.tags)

    lines: list[str] = [_yaml_frontmatter(fm)]

    lines.append(f"# {mdx_blocks.escape_mdx_text(page.title)}")
    lines.append("")
    if page.summary:
        lines.append(mdx_blocks.escape_mdx_text(page.summary))
        lines.append("")

    for block in page.blocks:
        lines.extend(mdx_blocks.format_block(block, mermaid_image_paths))
        lines.append("")

    bullets: list[str] = []
    for related_id in page.related:
        if related_id not in page_ids:
            continue
        # Page lives at /<group>/<id> when grouped, /<id> otherwise.
        if related_id in groups:
            href = f"/{groups[related_id]}/{related_id}"
        else:
            href = f"/{related_id}"
        bullets.append(f"- [{related_id}]({href})")
    if bullets:
        lines.append("## Related Pages")
        lines.append("")
        lines.extend(bullets)
        lines.append("")

    return "\n".join(lines)


def _ensure_index_page(
    content_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    groups: dict[str, str],
) -> None:
    """Ensure `content/index.mdx` exists.

    Without an index page, the root route may render the catch-all with an empty
    path and result in a 404. Links use the full route including the group
    prefix when a page is nested.
    """

    index_path = content_dir / "index.mdx"
    if index_path.exists():
        return

    lines: list[str] = [
        _yaml_frontmatter({"title": "Home", "description": "Generated documentation"}),
        "# Documentation",
        "",
        "Generated by source2doc bundler.",
        "",
    ]

    if navigation:
        lines.append("## Contents")
        lines.append("")
        for nav_id, data in navigation.items():
            if nav_id == "index":
                continue
            if isinstance(data, dict) and "children" in data:
                group_title = str(
                    data.get("title", nav_id.replace("-", " ").replace("_", " ").title())
                )
                lines.append(f"- **{group_title}**")
                for child_id, child_data in data["children"].items():
                    if child_id not in pages:
                        continue
                    child_title = _resolve_title(child_id, child_data, pages)
                    lines.append(f"    - [{child_title}](/{nav_id}/{child_id})")
            else:
                if nav_id not in pages:
                    continue
                title = _resolve_title(nav_id, data, pages)
                href = f"/{groups[nav_id]}/{nav_id}" if nav_id in groups else f"/{nav_id}"
                lines.append(f"- [{title}]({href})")
        lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("nextra_index_page_created", path=str(index_path))


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


def _generate_group_index_pages(
    content_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    extension: str,
) -> None:
    """Generate an `index.mdx` for every navigation group that has children.

    Nextra requires that every key in `_meta.js` corresponds to either a file or
    a directory.  When the planner creates a group section (e.g. ``bot-commands``
    with children ``find-command``, ``stop-command`` …) there is no page stored
    in the database for the group itself — it is purely a navigation container.

    We synthesise a minimal index page for each such group so that Nextra can
    resolve the route and render a table-of-contents style landing page.
    """
    for slug, data in navigation.items():
        if not (isinstance(data, dict) and "children" in data):
            continue

        group_dir = content_dir / slug
        group_dir.mkdir(parents=True, exist_ok=True)

        index_path = group_dir / f"index{extension}"
        if index_path.exists():
            # Already written (e.g. a real page with this id exists).
            continue

        title = str(data.get("title", slug.replace("-", " ").replace("_", " ").title()))
        children: dict[str, str | dict] = data["children"]

        lines: list[str] = [
            _yaml_frontmatter({"title": title}),
            f"# {mdx_blocks.escape_mdx_text(title)}",
            "",
        ]

        if children:
            lines.append("## Pages")
            lines.append("")
            for child_id, child_data in children.items():
                # Skip group children whose page got dropped (e.g. writer
                # max-retries → no row in DB). Linking a stale child here
                # would 404 in Nextra and the matching ``_meta.js`` entry
                # would also point nowhere.
                if child_id not in pages:
                    continue
                if isinstance(child_data, dict):
                    child_title = str(child_data.get("title", child_id))
                else:
                    child_title = str(child_data)
                if pages[child_id].title:
                    child_title = pages[child_id].title
                lines.append(f"- [{child_title}](./{child_id})")
            lines.append("")

        index_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("nextra_group_index_page_created", group=slug, path=str(index_path))


def _generate_meta_files(
    content_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    groups: dict[str, str],
) -> None:
    """Generate Nextra `_meta.js` files.

    In Nextra v4, `_meta.{js,jsx,ts,tsx}` files are supported both in `app/`
    and `content/` directories. When using the `content/` directory convention,
    `_meta.js` is collected from `content/`.

    Docs: https://nextra.site/docs/file-conventions/meta-file

    Navigation entries that are groups (have ``children``) are mapped to
    subdirectories.  Their children are placed inside those subdirectories and
    get their own ``_meta.js`` inside the subdirectory.
    """

    meta_by_rel_dir: dict[Path, dict[str, str]] = {}

    def ensure_dir(rel_dir: Path) -> dict[str, str]:
        return meta_by_rel_dir.setdefault(rel_dir, {})

    def add_page(rel_dir: Path, slug: str, title: str) -> None:
        meta = ensure_dir(rel_dir)
        meta.setdefault(slug, title)

    # Always create at least root meta with the index entry.
    if "index" in pages:
        index_title = pages["index"].title or "Home"
    else:
        index_title = "Home"
    add_page(Path("."), "index", index_title)

    # Walk the top-level navigation.
    for nav_id, nav_data in navigation.items():
        if nav_id == "index":
            continue

        if isinstance(nav_data, dict) and "children" in nav_data:
            # This is a group/section — it maps to a subdirectory.
            group_title = str(
                nav_data.get("title", nav_id.replace("-", " ").replace("_", " ").title())
            )
            # Add the group folder itself to the root _meta.js.
            add_page(Path("."), nav_id, group_title)

            # Add each child to the group's _meta.js — but skip children
            # whose page file is missing (writer failures drop the row).
            # Nextra 4 hard-fails the build with "field key X refers to a
            # page that cannot be found" if a `_meta` key has no matching
            # file or subdir, so we keep the meta in sync with what's on
            # disk.
            children: dict[str, str | dict] = nav_data["children"]
            # Always include the synthesised index page first.
            add_page(Path(nav_id), "index", group_title)
            for child_id, child_data in children.items():
                if child_id not in pages:
                    continue
                if isinstance(child_data, dict):
                    child_title = str(child_data.get("title", child_id))
                else:
                    child_title = str(child_data)
                if pages[child_id].title:
                    child_title = pages[child_id].title
                add_page(Path(nav_id), child_id, child_title)
        else:
            # Plain page — must have a corresponding .mdx file. Skip
            # nav entries whose page wasn't written (see comment above).
            if nav_id not in pages:
                continue

            title: str
            if isinstance(nav_data, str):
                title = nav_data
            else:
                title = str(nav_data)

            if pages[nav_id].title:
                title = pages[nav_id].title

            parts = [p for p in nav_id.split("/") if p and p not in (".", "..")]
            if not parts:
                continue

            rel_dir = Path(*parts[:-1]) if len(parts) > 1 else Path(".")
            slug = parts[-1]
            add_page(rel_dir, slug, title)

            # Ensure parent directories show up in the sidebar.
            if len(parts) > 1:
                parent_rel_dir = Path(*parts[:-2]) if len(parts) > 2 else Path(".")
                folder = parts[-2]
                add_page(parent_rel_dir, folder, folder.replace("-", " ").replace("_", " ").title())

    # Write all meta files.
    for rel_dir, meta in meta_by_rel_dir.items():
        target_dir = content_dir / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        # Use JSON serialization for safe quoting.
        meta_js = "export default " + json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
        meta_path = target_dir / "_meta.js"
        meta_path.write_text(meta_js, encoding="utf-8")
