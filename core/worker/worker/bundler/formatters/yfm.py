"""Yandex Flavored Markdown (YFM) formatter — Diplodoc target.

Produces a bundle that can be consumed by the Yandex Cloud documentation engine
(Diplodoc).  Reference: https://diplodoc.com/docs/en/syntax/

Key differences from generic GitHub-Flavored Markdown:

* Admonitions (callouts) are rendered as ``{% note <kind> %}…{% endnote %}``.
* Collapsible sections (cuts) use ``{% cut "title" %}…{% endcut %}``.
* Navigation lives in ``toc.yaml`` (instead of ``mkdocs.yml`` / ``_meta.js``).
* Mermaid diagrams stay as ``mermaid`` fenced blocks — Diplodoc renders them
  natively when the Mermaid plugin is enabled and degrades gracefully to a
  plain code block otherwise.
"""

from pathlib import Path
import typing as tp

import yaml

from source2doc.logging import get_logger
from source2doc.models import docs as doc_models

from worker.bundler import mermaid as mermaid_render
from worker.bundler.formatters import env as formatter_env


logger = get_logger(__name__)


# Map our internal callout variants onto YFM ``{% note %}`` kinds.
# YFM understands: info, tip, warning, alert.
_CALLOUT_KIND_MAP: dict[str, str] = {
    "info": "info",
    "warning": "warning",
    "error": "alert",
    "success": "tip",
}


async def format_bundle(
    env: formatter_env.YFMFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
    mermaid_render_mode: mermaid_render.MermaidRenderMode = "fence",
) -> None:
    """Write generated pages into a Diplodoc-compatible directory tree.

    ``mermaid_render_mode`` controls how Mermaid fences are emitted. When
    ``fence`` (the default for YFM, since Diplodoc renders Mermaid natively)
    the diagrams are kept as ```` ```mermaid ```` code blocks. When ``svg``
    or ``png`` they are pre-rendered with ``mmdc`` and replaced with image
    references — useful for Diplodoc deployments without the Mermaid plugin.
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    mermaid_paths = await mermaid_render.prerender_mermaid_for_pages(
        pages, output_dir, mermaid_render_mode
    )

    groups = _collect_groups(index.navigation)
    extension = env.get_file_extension()

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
        page_path.write_text(_format_page(page, mermaid_paths_rel), encoding="utf-8")

    _ensure_index_page(output_dir, pages, extension)
    _generate_group_index_pages(output_dir, index.navigation, pages, extension)


def _rewrite_relative_to(
    mermaid_paths: dict[str, str],
    depth: int,
) -> dict[str, str]:
    """Rewrite mermaid image paths so they are relative to a page at ``depth``."""
    if not mermaid_paths or depth == 0:
        return mermaid_paths
    prefix = "../" * depth
    return {diagram: f"{prefix}{rel}" for diagram, rel in mermaid_paths.items()}


async def generate_config(
    env: formatter_env.YFMFormatterEnv,
    output_dir: Path,
    config_data: dict[str, tp.Any],
) -> None:
    """Generate ``toc.yaml`` for the Diplodoc navigation tree."""

    toc = _build_toc(
        title=str(config_data.get("site_name", "Documentation")),
        navigation=config_data.get("navigation", {}),
        pages=config_data.get("pages") or {},
        extension=env.get_file_extension(),
    )

    toc_yaml = yaml.safe_dump(toc, allow_unicode=True, sort_keys=False)
    (output_dir / "toc.yaml").write_text(toc_yaml, encoding="utf-8")


async def generate_dockerfile(
    env: formatter_env.YFMFormatterEnv,
    output_dir: Path,
) -> None:
    """Diplodoc has no canonical self-host Dockerfile — write a tiny stub.

    Most users feed the bundle straight into ``yfm-docs`` / ``@diplodoc/cli``
    on their own infrastructure, so we ship a minimal builder image instead.
    """

    dockerfile = (
        "# Diplodoc / yfm-docs builder.\n"
        "# Build a static site from the bundled toc.yaml.\n"
        "FROM node:20-alpine\n"
        "WORKDIR /docs\n"
        "RUN npm install -g @diplodoc/cli\n"
        "COPY . /docs\n"
        'CMD ["yfm", "-i", "/docs", "-o", "/docs/_build"]\n'
    )
    (output_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")


# --------------------------------------------------------------------------- #
#                              Page rendering
# --------------------------------------------------------------------------- #


def _format_page(
    page: doc_models.DocPage,
    mermaid_image_paths: dict[str, str] | None = None,
) -> str:
    lines: list[str] = []

    lines.append(f"# {page.title}")
    lines.append("")
    if page.summary:
        lines.append(page.summary)
        lines.append("")

    for block in page.blocks:
        lines.extend(_format_block(block, mermaid_image_paths))
        lines.append("")

    if page.related:
        lines.append("## Related Pages")
        lines.append("")
        for related_id in page.related:
            lines.append(f"- [{related_id}](./{related_id}.md)")
        lines.append("")

    return "\n".join(lines)


def _format_block(
    block: doc_models.DocBlock,
    mermaid_image_paths: dict[str, str] | None = None,
) -> list[str]:
    """YFM-specific block dispatcher.

    Falls back to the generic markdown shapes from ``source2doc.formatter.mdx``
    for everything that doesn't need YFM-specific syntax.
    """

    match block:
        case doc_models.HeadingBlock():
            return [f"{'#' * block.level} {block.text}"]
        case doc_models.ParagraphBlock():
            return [block.text]
        case doc_models.CodeBlock():
            return [f"```{block.lang}", block.code, "```"]
        case doc_models.ListBlock():
            return _format_list(block)
        case doc_models.TableBlock():
            return _format_table(block)
        case doc_models.CalloutBlock():
            return _format_callout(block)
        case doc_models.MermaidBlock():
            if mermaid_image_paths and block.diagram in mermaid_image_paths:
                rel = mermaid_image_paths[block.diagram]
                alt = "Mermaid diagram"
                return [f"![{alt}]({rel})"]
            return ["```mermaid", block.diagram, "```"]
        case doc_models.CutBlock():
            return _format_cut(block, mermaid_image_paths)
        case doc_models.ImageBlock():
            return _format_image(block)
        case _:
            return []


def _format_list(block: doc_models.ListBlock) -> list[str]:
    lines: list[str] = []
    for idx, item in enumerate(block.items):
        prefix = f"{idx + 1}." if block.ordered else "-"
        lines.append(f"{prefix} {item.text}")
    return lines


def _format_table(block: doc_models.TableBlock) -> list[str]:
    # Diplodoc supports GFM tables verbatim.
    lines = ["| " + " | ".join(block.headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(block.headers)) + " |")
    for row in block.rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _format_callout(block: doc_models.CalloutBlock) -> list[str]:
    """Emit a YFM ``{% note %}`` admonition block."""
    kind = _CALLOUT_KIND_MAP.get(block.variant, "info")
    return [
        f"{{% note {kind} %}}",
        "",
        block.text,
        "",
        "{% endnote %}",
    ]


def _format_cut(
    block: doc_models.CutBlock,
    mermaid_image_paths: dict[str, str] | None = None,
) -> list[str]:
    """Emit a YFM ``{% cut %}`` collapsible block."""
    title = block.title.replace('"', '\\"')
    lines = [f'{{% cut "{title}" %}}', ""]
    for nested_block in block.blocks:
        lines.extend(_format_block(nested_block, mermaid_image_paths))
        lines.append("")
    lines.append("{% endcut %}")
    return lines


def _format_image(block: doc_models.ImageBlock) -> list[str]:
    alt_text = block.alt or ""
    caption = f"\n*{block.caption}*" if block.caption else ""
    return [f"![{alt_text}]({block.src}){caption}"]


# --------------------------------------------------------------------------- #
#                              Navigation / toc.yaml
# --------------------------------------------------------------------------- #


def _collect_groups(navigation: dict[str, str | dict]) -> dict[str, str]:
    """Map ``child_page_id -> group_slug`` for every navigation group."""
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


def _build_toc(
    title: str,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    extension: str,
) -> dict[str, tp.Any]:
    """Build the ``toc.yaml`` payload Diplodoc expects.

    Shape::

        title: My Docs
        items:
          - name: Overview
            href: index.md
          - name: Group A
            items:
              - name: Page 1
                href: group-a/page-1.md
    """

    items: list[dict[str, tp.Any]] = []
    if "index" not in navigation:
        # Always surface the root index page first if it exists or is synthesised.
        index_title = pages["index"].title if "index" in pages else "Overview"
        items.append({"name": index_title, "href": f"index{extension}"})

    for nav_id, nav_data in navigation.items():
        if isinstance(nav_data, dict) and "children" in nav_data:
            group_title = str(nav_data.get("title", _humanise(nav_id)))
            child_items: list[dict[str, tp.Any]] = [
                {"name": group_title, "href": f"{nav_id}/index{extension}"},
            ]
            children: dict[str, str | dict] = nav_data["children"]
            for child_id, child_data in children.items():
                child_title = _resolve_title(child_id, child_data, pages)
                child_items.append(
                    {"name": child_title, "href": f"{nav_id}/{child_id}{extension}"},
                )
            items.append({"name": group_title, "items": child_items})
        else:
            page_title = _resolve_title(nav_id, nav_data, pages)
            items.append({"name": page_title, "href": f"{nav_id}{extension}"})

    return {"title": title, "items": items}


def _resolve_title(
    page_id: str,
    nav_data: str | dict | None,
    pages: dict[str, doc_models.DocPage],
) -> str:
    if page_id in pages and pages[page_id].title:
        return pages[page_id].title
    if isinstance(nav_data, dict):
        return str(nav_data.get("title", _humanise(page_id)))
    if isinstance(nav_data, str) and nav_data:
        return nav_data
    return _humanise(page_id)


def _humanise(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _ensure_index_page(
    output_dir: Path,
    pages: dict[str, doc_models.DocPage],
    extension: str,
) -> None:
    """Synthesise a root ``index.md`` if no real one was generated."""
    index_path = output_dir / f"index{extension}"
    if index_path.exists():
        return

    lines: list[str] = ["# Documentation", "", "Generated by source2doc bundler.", ""]
    if pages:
        lines.append("## Pages")
        lines.append("")
        for page_id, page in pages.items():
            if page_id == "index":
                continue
            lines.append(f"- [{page.title}](./{page_id}{extension})")
        lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("yfm_index_page_created", path=str(index_path))


def _generate_group_index_pages(
    output_dir: Path,
    navigation: dict[str, str | dict],
    pages: dict[str, doc_models.DocPage],
    extension: str,
) -> None:
    """Generate ``<group>/index.md`` landing pages for each navigation group."""
    for slug, data in navigation.items():
        if not (isinstance(data, dict) and "children" in data):
            continue

        group_dir = output_dir / slug
        group_dir.mkdir(parents=True, exist_ok=True)
        index_path = group_dir / f"index{extension}"
        if index_path.exists():
            continue

        title = str(data.get("title", _humanise(slug)))
        children: dict[str, str | dict] = data["children"]

        lines = [f"# {title}", ""]
        if children:
            lines.append("## Pages")
            lines.append("")
            for child_id, child_data in children.items():
                child_title = _resolve_title(child_id, child_data, pages)
                lines.append(f"- [{child_title}](./{child_id}{extension})")
            lines.append("")

        index_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("yfm_group_index_page_created", group=slug, path=str(index_path))
