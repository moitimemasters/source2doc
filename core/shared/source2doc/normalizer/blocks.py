"""Pure block-level normalization passes.

Each pass takes ``list[DocBlock]`` and returns a new list, plus an integer
edit count. Reasoning lives in the docstrings — these are the rules the
LLM second-pass falls back to when it isn't invoked.
"""

from __future__ import annotations

import dataclasses as dc
import re

from source2doc.models.docs import (
    CodeBlock,
    DocBlock,
    HeadingBlock,
    ListBlock,
    ListItem,
    MermaidPlaceholderBlock,
    ParagraphBlock,
    walk_blocks,
)


_HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_FENCED_CODE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```", re.MULTILINE)
_BULLET_LINE_RE = re.compile(r"^\s*[-*+]\s+(.+)$")
_ORDERED_LINE_RE = re.compile(r"^\s*\d+[.)]\s+(.+)$")


@dc.dataclass
class NormalizationReport:
    """Counts of edits each pass made.

    ``total`` is what the handler compares against
    ``NormalizerConfig.llm_threshold_edits`` to decide whether to follow
    up with the LLM second-pass.
    """

    inline_headings_split: int = 0
    fenced_code_extracted: int = 0
    inline_lists_extracted: int = 0
    heading_levels_normalized: int = 0
    dead_placeholders_replaced: int = 0

    @property
    def total(self) -> int:
        return (
            self.inline_headings_split
            + self.fenced_code_extracted
            + self.inline_lists_extracted
            + self.heading_levels_normalized
            + self.dead_placeholders_replaced
        )


def split_inline_headings(blocks: list[DocBlock]) -> tuple[list[DocBlock], int]:
    """Promote ``## ...`` lines that ended up inside ``paragraph`` text into
    real ``heading`` blocks. Single most common writer drift on weak models.
    """

    out: list[DocBlock] = []
    edits = 0
    for block in blocks:
        if not isinstance(block, ParagraphBlock):
            out.append(block)
            continue

        lines = block.text.split("\n")
        if not any(_HEADING_LINE_RE.match(line) for line in lines):
            out.append(block)
            continue

        buffer: list[str] = []

        def _flush() -> None:
            if buffer:
                joined = "\n".join(buffer).strip()
                if joined:
                    out.append(ParagraphBlock(text=joined))
                buffer.clear()

        for line in lines:
            m = _HEADING_LINE_RE.match(line)
            if m:
                _flush()
                level = len(m.group(1))
                text = m.group(2).strip()
                if text:
                    out.append(HeadingBlock(level=min(level, 6), text=text))
                    edits += 1
            else:
                buffer.append(line)
        _flush()

    return out, edits


def extract_fenced_code(blocks: list[DocBlock]) -> tuple[list[DocBlock], int]:
    """Pull ``` ```lang\\n...\\n``` ``` fences out of paragraph text into ``code``
    blocks. Writers occasionally emit a fenced block as paragraph markdown.
    """

    out: list[DocBlock] = []
    edits = 0
    for block in blocks:
        if not isinstance(block, ParagraphBlock) or "```" not in block.text:
            out.append(block)
            continue

        text = block.text
        last_end = 0
        local_edits = 0
        for match in _FENCED_CODE_RE.finditer(text):
            before = text[last_end : match.start()].strip()
            if before:
                out.append(ParagraphBlock(text=before))
            lang = match.group(1) or "text"
            code = match.group(2).rstrip()
            if code.strip():
                out.append(CodeBlock(lang=lang, code=code))
                local_edits += 1
            last_end = match.end()
        tail = text[last_end:].strip()
        if local_edits == 0:
            out.append(block)
        else:
            if tail:
                out.append(ParagraphBlock(text=tail))
            edits += local_edits

    return out, edits


def extract_inline_lists(blocks: list[DocBlock]) -> tuple[list[DocBlock], int]:
    """Convert paragraphs that are entirely bullet/numbered lines into
    ``list`` blocks. Conservative: requires every non-empty line to match.
    """

    out: list[DocBlock] = []
    edits = 0
    for block in blocks:
        if not isinstance(block, ParagraphBlock):
            out.append(block)
            continue

        lines = [line for line in block.text.split("\n") if line.strip()]
        if len(lines) < 2:
            out.append(block)
            continue

        bullets = [_BULLET_LINE_RE.match(line) for line in lines]
        ordered = [_ORDERED_LINE_RE.match(line) for line in lines]
        if all(bullets):
            out.append(
                ListBlock(
                    ordered=False,
                    items=[ListItem(text=m.group(1).strip()) for m in bullets if m],
                )
            )
            edits += 1
        elif all(ordered):
            out.append(
                ListBlock(
                    ordered=True,
                    items=[ListItem(text=m.group(1).strip()) for m in ordered if m],
                )
            )
            edits += 1
        else:
            out.append(block)

    return out, edits


def normalize_heading_levels(blocks: list[DocBlock]) -> tuple[list[DocBlock], int]:
    """Prevent heading-level skips: each heading may stay or jump at most
    one level deeper than the previous heading. ``# A`` then ``### B``
    becomes ``# A`` then ``## B``. The first heading keeps its original
    level — promoting it would clobber pages whose canonical title sits
    in :class:`DocPage.title` rather than block 0.
    """

    out = list(blocks)
    edits = 0
    prev_level: int | None = None
    for parent, idx, block in walk_blocks(out):
        if not isinstance(block, HeadingBlock):
            continue
        new_level = block.level
        if prev_level is not None:
            ceiling = prev_level + 1
            if new_level > ceiling:
                new_level = ceiling
                edits += 1
        if new_level != block.level:
            parent[idx] = HeadingBlock(level=new_level, text=block.text)
        prev_level = new_level
    return out, edits


def replace_dead_placeholders(blocks: list[DocBlock]) -> tuple[list[DocBlock], int]:
    """Replace any ``mermaid_placeholder`` block that survived the diagram
    phase with a ``CalloutBlock`` warning. The fronted already does this
    fallback at render-time (see ``ContentRenderer.tsx``), but persisting
    the resolved form means bundle exports and offline consumers never see
    a half-finished draft.
    """

    from source2doc.models.docs import CalloutBlock

    out = list(blocks)
    edits = 0
    for parent, idx, block in walk_blocks(out):
        if not isinstance(block, MermaidPlaceholderBlock):
            continue
        intent = block.intent.strip() or block.placeholder_id
        parent[idx] = CalloutBlock(
            variant="warning",
            text=f"Diagram unavailable: {intent}",
        )
        edits += 1
    return out, edits


def normalize_blocks(blocks: list[DocBlock]) -> tuple[list[DocBlock], NormalizationReport]:
    """Run every deterministic pass in order and collect a single report.

    Order matters: split inline headings BEFORE list extraction (so a
    paragraph that mixes ``## Header`` with bullet lines fans out
    correctly), and extract fenced code BEFORE level normalization (so
    code blocks don't influence heading numbering).
    """

    report = NormalizationReport()

    blocks, edits = split_inline_headings(blocks)
    report.inline_headings_split = edits

    blocks, edits = extract_fenced_code(blocks)
    report.fenced_code_extracted = edits

    blocks, edits = extract_inline_lists(blocks)
    report.inline_lists_extracted = edits

    blocks, edits = normalize_heading_levels(blocks)
    report.heading_levels_normalized = edits

    blocks, edits = replace_dead_placeholders(blocks)
    report.dead_placeholders_replaced = edits

    return blocks, report
