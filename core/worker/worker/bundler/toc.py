"""Full Table of Contents autogeneration for exported bundles.

Closes ТЗ ЭКС-08. After a formatter writes its pages, :func:`build_toc` walks
every ``.md``/``.mdx``/``.rst`` file in the bundle directory, extracts h1/h2/...
headings (configurable depth), and produces a single machine-readable
``toc.json`` plus a human-readable ``_toc.md`` at the bundle root.

The format-specific indexes (``mkdocs.yml``, ``_meta.js``, ``index.rst``) are
left untouched — these ToC files coexist with them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re

from source2doc.logging import get_logger


logger = get_logger(__name__)


# Directory names skipped when walking the bundle tree.  ``diagrams/`` holds
# generated mermaid SVGs; the others are framework artefacts that never carry
# meaningful documentation headings.
_SKIP_DIRS = frozenset(
    {
        "diagrams",
        "node_modules",
        ".next",
        "_build",
        "build",
        "dist",
        ".venv",
        "__pycache__",
        ".git",
    }
)

_DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst"})

# RST title underline characters. The first time a level is seen its char is
# remembered; from then on the same char always means the same depth.  This is
# the rule docutils itself uses.
_RST_UNDERLINE_CHARS = "=-~^\"'+#*<>:_"

# Anything between matching triple-backtick fences (or matching tildes) is
# code, not prose, and must not contribute headings.  We tolerate optional
# language identifiers after the opener (e.g. ``` ```python ```).
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

_MD_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")


@dataclass(slots=True)
class Heading:
    """A single heading extracted from a documentation file."""

    level: int
    text: str
    anchor: str


@dataclass(slots=True)
class TocEntry:
    """One file's contribution to the bundle ToC."""

    path: str
    title: str | None
    headings: list[Heading] = field(default_factory=list)


@dataclass(slots=True)
class ToC:
    """The full bundle ToC."""

    max_depth: int
    entries: list[TocEntry] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#                              slugify
# --------------------------------------------------------------------------- #


_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_HYPHEN_RE = re.compile(r"[\s_]+")


def slugify(text: str) -> str:
    """Convert a heading to a GitHub-style anchor.

    Lowercases, drops punctuation, collapses whitespace/underscores into a
    single hyphen.  Pure stdlib + regex — no external dep.
    """
    cleaned = _SLUG_STRIP_RE.sub("", text.strip().lower())
    return _SLUG_HYPHEN_RE.sub("-", cleaned).strip("-")


# --------------------------------------------------------------------------- #
#                              Markdown extractor
# --------------------------------------------------------------------------- #


def extract_headings_from_md(text: str, max_depth: int = 2) -> list[Heading]:
    """Extract Markdown headings up to ``max_depth``.

    The parser is intentionally line-based: scans for ``^#{1,N} text`` while
    tracking fenced code blocks (``` or ~~~) so headings inside code do not
    leak into the ToC.  ATX-style only — Setext underlines are uncommon in
    generated MDX/MD and would collide with RST detection.
    """
    if max_depth <= 0:
        return []

    headings: list[Heading] = []
    in_fence = False
    fence_marker: str | None = None

    for raw in text.splitlines():
        fence_match = _FENCE_RE.match(raw)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif fence_marker == marker:
                in_fence = False
                fence_marker = None
            continue

        if in_fence:
            continue

        match = _MD_HEADING_RE.match(raw)
        if not match:
            continue

        level = len(match.group("hashes"))
        if level > max_depth:
            continue

        heading_text = match.group("text").strip()
        if not heading_text:
            continue

        headings.append(Heading(level=level, text=heading_text, anchor=slugify(heading_text)))

    return headings


# --------------------------------------------------------------------------- #
#                              RST extractor
# --------------------------------------------------------------------------- #


def extract_headings_from_rst(text: str, max_depth: int = 2) -> list[Heading]:
    """Extract reStructuredText section titles up to ``max_depth``.

    RST sections are denoted by an underline (and optionally an overline) of
    repeated punctuation under the title.  We track which characters have been
    used in source order; the first one seen is depth 1, the second is depth
    2, and so on — same convention as docutils.
    """
    if max_depth <= 0:
        return []

    lines = text.splitlines()
    headings: list[Heading] = []
    seen_chars: list[str] = []

    in_fence = False
    fence_marker: str | None = None
    i = 0
    while i < len(lines) - 1:
        line = lines[i]

        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif fence_marker == marker:
                in_fence = False
                fence_marker = None
            i += 1
            continue

        if in_fence:
            i += 1
            continue

        title = line.strip()
        underline = lines[i + 1] if i + 1 < len(lines) else ""

        if (
            title
            and underline
            and len(underline) >= len(title)
            and underline[0] in _RST_UNDERLINE_CHARS
            and underline == underline[0] * len(underline)
        ):
            char = underline[0]
            if char not in seen_chars:
                seen_chars.append(char)
            level = seen_chars.index(char) + 1
            if level <= max_depth:
                headings.append(Heading(level=level, text=title, anchor=slugify(title)))
            # Skip the underline so we don't re-process it as content.
            i += 2
            continue

        i += 1

    return headings


# --------------------------------------------------------------------------- #
#                              Bundle walker
# --------------------------------------------------------------------------- #


def _extract_for_path(path: Path, max_depth: int) -> list[Heading]:
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        logger.warning("toc_skip_unreadable_file", path=str(path), error=str(exc))
        return []

    if suffix == ".rst":
        return extract_headings_from_rst(text, max_depth=max_depth)
    # Treat .md / .mdx (and anything else that slipped through the suffix
    # filter) with the markdown parser.
    return extract_headings_from_md(text, max_depth=max_depth)


def _file_title(path: Path, headings: list[Heading]) -> str | None:
    """Pick a display title for the file: first h1 if present, else None."""
    for h in headings:
        if h.level == 1:
            return h.text
    return None


def _iter_doc_files(bundle_dir: Path) -> list[Path]:
    """Walk ``bundle_dir`` returning .md/.mdx/.rst files in stable order.

    Skips :data:`_SKIP_DIRS` anywhere in the tree.
    """
    results: list[Path] = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _DOC_SUFFIXES:
            continue
        rel_parts = path.relative_to(bundle_dir).parts
        if any(part in _SKIP_DIRS for part in rel_parts[:-1]):
            continue
        results.append(path)
    return results


def build_toc(bundle_dir: Path, max_depth: int = 2) -> ToC:
    """Walk ``bundle_dir`` and assemble a :class:`ToC`.

    ``max_depth`` of ``0`` produces an empty ToC (caller can use this to
    disable generation by simply not invoking :func:`write_toc_json`/``_md``).
    """
    toc = ToC(max_depth=max_depth)
    if max_depth <= 0:
        return toc

    for path in _iter_doc_files(bundle_dir):
        headings = _extract_for_path(path, max_depth)
        rel = path.relative_to(bundle_dir).as_posix()
        toc.entries.append(
            TocEntry(
                path=rel,
                title=_file_title(path, headings),
                headings=headings,
            )
        )
    return toc


# --------------------------------------------------------------------------- #
#                              Writers
# --------------------------------------------------------------------------- #


def write_toc_json(toc: ToC, out: Path) -> None:
    """Dump the ToC as machine-readable JSON."""
    payload = {
        "max_depth": toc.max_depth,
        "entries": [asdict(e) for e in toc.entries],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_toc_md(toc: ToC, out: Path) -> None:
    """Render the ToC as a nested bullet list with file links.

    Output shape::

        # Full Table of Contents

        - [Intro](./intro.md)
          - [Getting Started](./intro.md#getting-started)
        - [Group / Page 1](./group/page1.md)
          - [Section](./group/page1.md#section)
    """
    lines: list[str] = ["# Full Table of Contents", ""]

    if not toc.entries:
        lines.append("_No documentation pages found._")
        lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return

    for entry in toc.entries:
        display = entry.title or entry.path
        lines.append(f"- [{display}](./{entry.path})")
        for heading in entry.headings:
            if heading.level == 1:
                # Already represented as the entry title link.
                continue
            indent = "  " * (heading.level - 1)
            lines.append(f"{indent}- [{heading.text}](./{entry.path}#{heading.anchor})")
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")


def generate_toc_files(bundle_dir: Path, max_depth: int = 2) -> ToC | None:
    """Convenience wrapper used by the bundler processor.

    Returns the built :class:`ToC` (or ``None`` when ``max_depth <= 0``) so
    callers can log/inspect it.  Writes ``toc.json`` and ``_toc.md`` into
    ``bundle_dir``.
    """
    if max_depth <= 0:
        logger.info("toc_generation_disabled", bundle_dir=str(bundle_dir))
        return None

    toc = build_toc(bundle_dir, max_depth=max_depth)
    write_toc_json(toc, bundle_dir / "toc.json")
    write_toc_md(toc, bundle_dir / "_toc.md")
    logger.info(
        "toc_generated",
        bundle_dir=str(bundle_dir),
        files=len(toc.entries),
        max_depth=max_depth,
    )
    return toc
