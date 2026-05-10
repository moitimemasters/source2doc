"""Shared ``mmdc`` subprocess plumbing.

Single source of truth for invoking ``@mermaid-js/mermaid-cli`` (``mmdc``).
The bundler uses :func:`render_mermaid` to produce static SVG/PNG; the
diagram phase of the docgen pipeline uses :func:`validate_mermaid` to
confirm the agent's output compiles before committing it to the page.

If ``mmdc`` is missing in the environment (no Node, no Chromium) every
function returns a soft failure so the caller can degrade gracefully.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
from typing import Literal

from source2doc.logging import get_logger
from source2doc.models.mermaid_kinds import MermaidKind


logger = get_logger(__name__)


MermaidFormat = Literal["svg", "png"]

DEFAULT_RENDER_TIMEOUT_SECONDS = 30.0


def _puppeteer_args() -> list[str]:
    puppeteer_config = os.environ.get("MMDC_PUPPETEER_CONFIG_FILE")
    if puppeteer_config:
        return ["--puppeteerConfigFile", puppeteer_config]
    return []


async def run_mmdc(
    diagram_text: str,
    out_path: Path,
    fmt: MermaidFormat,
    timeout_seconds: float = DEFAULT_RENDER_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Invoke ``mmdc`` once, piping ``diagram_text`` on stdin.

    Returns ``(ok, stderr_text)``. Stderr is truncated to 2 KiB so it can be
    shoved back into an LLM prompt without blowing the context window.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = [
        "mmdc",
        "--input",
        "-",
        "--output",
        str(out_path),
        "--backgroundColor",
        "transparent",
        "--outputFormat",
        fmt,
        *_puppeteer_args(),
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.warning(
            "mermaid_cli_not_found",
            hint="install @mermaid-js/mermaid-cli (mmdc) in the worker image",
        )
        return False, "mmdc not installed"

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=diagram_text.encode("utf-8")),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        logger.warning("mermaid_render_timeout", out_path=str(out_path))
        return False, f"mmdc timed out after {timeout_seconds}s"

    stderr_text = stderr.decode("utf-8", errors="replace")[:2048]

    if process.returncode != 0:
        logger.warning(
            "mermaid_render_failed",
            returncode=process.returncode,
            stderr=stderr_text[:500],
            stdout=stdout.decode("utf-8", errors="replace")[:200],
        )
        return False, stderr_text

    if not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning("mermaid_render_empty_output", out_path=str(out_path))
        return False, "empty mmdc output"

    return True, ""


async def validate_mermaid(
    diagram_text: str,
    kind: MermaidKind | None = None,
    timeout_seconds: float = DEFAULT_RENDER_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Compile ``diagram_text`` with ``mmdc`` to a throwaway SVG.

    Returns ``(ok, stderr)``. Used by the diagram phase to confirm the
    agent emitted parseable mermaid before patching the page. ``kind`` is
    accepted for symmetry but mmdc parses the diagram header itself.
    """
    del kind
    with tempfile.TemporaryDirectory(prefix="mmdc-validate-") as tmpdir:
        out_path = Path(tmpdir) / "out.svg"
        return await run_mmdc(diagram_text, out_path, "svg", timeout_seconds)


async def render_mermaid(
    diagram_text: str,
    out_path: Path,
    fmt: MermaidFormat,
    timeout_seconds: float = DEFAULT_RENDER_TIMEOUT_SECONDS,
) -> bool:
    """Render to a real file path. Used by the bundler for SVG/PNG export."""
    ok, _ = await run_mmdc(diagram_text, out_path, fmt, timeout_seconds)
    return ok
