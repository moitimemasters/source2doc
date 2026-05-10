"""Mermaid → SVG/PNG rendering helpers for the bundler worker.

Bundler can optionally pre-render ```` ```mermaid ```` fences to static images
(SVG/PNG) and replace the fenced block in the rendered output with an image
reference. This is useful for target platforms that don't run JS-side Mermaid
renderers (plain GFM viewers without JS, PDF exports, Sphinx without
extensions, etc.).

Implementation uses ``@mermaid-js/mermaid-cli`` (``mmdc``) shelled out via
``asyncio.create_subprocess_exec``. mmdc itself drives a Puppeteer-bundled
chromium to do the actual rendering.

If ``mmdc`` is unavailable or a render fails, callers should fall back to
keeping the original ```` ```mermaid ```` fence.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Literal

from source2doc.logging import get_logger
from source2doc.mermaid import MermaidFormat, render_mermaid
from source2doc.models import docs as doc_models


logger = get_logger(__name__)


MermaidRenderMode = Literal["fence", "svg", "png"]


__all__ = [
    "MermaidFormat",
    "MermaidRenderMode",
    "diagram_hash",
    "render_mermaid",
    "prerender_mermaid_for_pages",
    "MAX_DIAGRAMS_PER_BUNDLE",
    "RENDER_CONCURRENCY",
    "RENDER_TIMEOUT_SECONDS",
    "MERMAID_OUTPUT_SUBDIR",
    "MERMAID_IMAGE_MARKER",
]


# Cap diagrams per bundle to a safe number — guards against runaway specs.
MAX_DIAGRAMS_PER_BUNDLE = 1000

# Render up to this many diagrams in parallel.
RENDER_CONCURRENCY = 4

# Per-diagram render timeout (seconds).
RENDER_TIMEOUT_SECONDS = 30.0

# Subdirectory inside the bundle root where image artifacts go.
MERMAID_OUTPUT_SUBDIR = "mermaid"

# Marker line written into Markdown/RST output instead of a ``mermaid`` fence
# when rendering succeeded. Formatters use this to emit the appropriate image
# reference syntax for their target format.
MERMAID_IMAGE_MARKER = "__MERMAID_IMAGE__"


def diagram_hash(diagram_text: str) -> str:
    """Stable filename-friendly hash for a mermaid diagram body."""
    return hashlib.sha256(diagram_text.encode("utf-8")).hexdigest()[:16]


def _iter_mermaid_blocks(blocks: list[doc_models.DocBlock]):
    """Yield every ``MermaidBlock`` reachable from a page's blocks list.

    Recurses into ``CutBlock.blocks`` since Mermaid can nest inside collapsibles.
    """
    for block in blocks:
        if isinstance(block, doc_models.MermaidBlock):
            yield block
        elif isinstance(block, doc_models.CutBlock):
            yield from _iter_mermaid_blocks(block.blocks)


async def prerender_mermaid_for_pages(
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
    mode: MermaidRenderMode,
) -> dict[str, str]:
    """Render every mermaid diagram in ``pages`` to a static image.

    Returns a mapping ``diagram_text -> relative_image_path`` (relative to
    ``output_dir``) for each successful render. Diagrams that fail to render
    or that exceed ``MAX_DIAGRAMS_PER_BUNDLE`` are absent from the result;
    formatters fall back to the original ```` ```mermaid ```` fence for those.

    When ``mode == "fence"`` this is a no-op and returns an empty dict.
    """

    if mode == "fence":
        return {}

    fmt: MermaidFormat = mode  # type: ignore[assignment]

    # Collect unique diagrams (dedupe by text — same diagram on multiple pages
    # should render once).
    unique_diagrams: dict[str, str] = {}
    for page in pages.values():
        for block in _iter_mermaid_blocks(page.blocks):
            unique_diagrams.setdefault(block.diagram, diagram_hash(block.diagram))
            if len(unique_diagrams) >= MAX_DIAGRAMS_PER_BUNDLE:
                break
        if len(unique_diagrams) >= MAX_DIAGRAMS_PER_BUNDLE:
            logger.warning(
                "mermaid_diagram_cap_exceeded",
                cap=MAX_DIAGRAMS_PER_BUNDLE,
            )
            break

    if not unique_diagrams:
        return {}

    mermaid_dir = output_dir / MERMAID_OUTPUT_SUBDIR
    mermaid_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(RENDER_CONCURRENCY)
    rel_paths: dict[str, str] = {}

    async def _one(diagram: str, sha: str) -> None:
        rel = f"{MERMAID_OUTPUT_SUBDIR}/{sha}.{fmt}"
        out_path = output_dir / rel
        async with semaphore:
            ok = await render_mermaid(diagram, out_path, fmt)
        if ok:
            rel_paths[diagram] = rel
        else:
            logger.info("mermaid_render_fallback_to_fence", sha=sha)

    await asyncio.gather(
        *(_one(diagram, sha) for diagram, sha in unique_diagrams.items()),
    )

    logger.info(
        "mermaid_prerender_done",
        rendered=len(rel_paths),
        total=len(unique_diagrams),
        mode=mode,
    )

    return rel_paths
