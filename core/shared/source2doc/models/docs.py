from collections.abc import Iterator
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from source2doc.models.mermaid_kinds import MermaidKind


# ============================================================================
# Block Types
# ============================================================================


class HeadingBlock(BaseModel):
    """Heading block (h1-h6)."""

    type: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=6, description="Heading level (1-6)")
    text: str = Field(description="Heading text (supports Markdown)")


class ParagraphBlock(BaseModel):
    """Text paragraph block."""

    type: Literal["paragraph"] = "paragraph"
    text: str = Field(description="Paragraph text (supports Markdown)")


class CodeBlock(BaseModel):
    """Code block with syntax highlighting."""

    type: Literal["code"] = "code"
    lang: str = Field(description="Programming language (python, javascript, etc.)")
    code: str = Field(description="Source code")


class ListItem(BaseModel):
    """Single list item."""

    text: str = Field(description="Item text (supports Markdown)")


class ListBlock(BaseModel):
    """Ordered or unordered list."""

    type: Literal["list"] = "list"
    ordered: bool = Field(description="True for numbered list, False for bullet list")
    items: list[ListItem] = Field(description="List items")


class TableBlock(BaseModel):
    """Table with headers and rows."""

    type: Literal["table"] = "table"
    headers: list[str] = Field(description="Column headers")
    rows: list[list[str]] = Field(description="Table rows")


class CalloutBlock(BaseModel):
    """Highlighted callout block."""

    type: Literal["callout"] = "callout"
    variant: Literal["info", "warning", "error", "success"] = Field(description="Callout type")
    text: str = Field(description="Callout text (supports Markdown)")


class MermaidBlock(BaseModel):
    """Mermaid diagram."""

    type: Literal["mermaid"] = "mermaid"
    diagram: str = Field(description="Mermaid diagram code")


class MermaidPlaceholderBlock(BaseModel):
    """Stub emitted by the writer; replaced by ``MermaidBlock`` (or a
    fallback ``CalloutBlock``) by the diagram phase of the pipeline."""

    type: Literal["mermaid_placeholder"] = "mermaid_placeholder"
    placeholder_id: str = Field(description="Stable id, unique within the page")
    kind: MermaidKind = Field(description="Mermaid diagram kind")
    intent: str = Field(description="What the diagram should show, 1-2 sentences")
    anchors: list[str] = Field(
        default_factory=list,
        description=(
            "Code entities the diagrammer should ground on "
            "(class names, file paths, function names)"
        ),
    )


class CutBlock(BaseModel):
    """Collapsible section."""

    type: Literal["cut"] = "cut"
    title: str = Field(description="Section title (supports Markdown)")
    default_open: bool = Field(default=False, description="Open by default")
    blocks: list["DocBlock"] = Field(description="Nested blocks")


class ImageBlock(BaseModel):
    """Image with caption."""

    type: Literal["image"] = "image"
    src: str = Field(description="Image source URL or path")
    alt: str = Field(description="Alternative text")
    caption: str | None = Field(default=None, description="Image caption (supports Markdown)")


# Union of all block types
DocBlock = (
    HeadingBlock
    | ParagraphBlock
    | CodeBlock
    | ListBlock
    | TableBlock
    | CalloutBlock
    | MermaidBlock
    | MermaidPlaceholderBlock
    | CutBlock
    | ImageBlock
)

# Update forward references for CutBlock
CutBlock.model_rebuild()


def walk_blocks(
    blocks: list["DocBlock"],
) -> Iterator[tuple[list["DocBlock"], int, "DocBlock"]]:
    """Yield ``(parent_list, index, block)`` for every block, recursing into
    ``CutBlock.blocks``. The ``parent_list`` is the actual list the block
    lives in, so callers can mutate it in place.
    """
    for index, block in enumerate(blocks):
        yield blocks, index, block
        if isinstance(block, CutBlock):
            yield from walk_blocks(block.blocks)


# ============================================================================
# Page Models
# ============================================================================


class SourceRef(BaseModel):
    """Reference to a source-file range that backs a page (or page section).

    Used by the UI to render "View source" deep-links into the configured
    git host. ``end_line`` is inclusive; if omitted or equal to
    ``start_line`` the link points at a single line.
    """

    file_path: str = Field(description="Repo-relative path, e.g. 'src/foo/bar.py'")
    start_line: int = Field(ge=1, description="1-indexed start line")
    end_line: int | None = Field(
        default=None,
        ge=1,
        description="1-indexed end line (inclusive); None for a single-line ref",
    )


class PageMetadata(BaseModel):
    """Page metadata."""

    generated_at: str = Field(default="", description="ISO 8601 timestamp")
    reading_time: int = Field(default=0, description="Estimated reading time in minutes")
    tags: list[str] = Field(default_factory=list, description="Page tags")
    commit_sha: str | None = Field(
        default=None,
        description="Source-repo commit SHA the page was generated against (B11.1)",
    )
    source_refs: list[SourceRef] = Field(
        default_factory=list,
        description=(
            "Optional list of source-file ranges this page references. The first entry "
            "is treated as the page's primary source for UI deep-links. (B6.5)"
        ),
    )


class DocPage(BaseModel):
    """Single documentation page."""

    title: str = Field(description="Page title")
    summary: str = Field(description="Brief page summary")
    metadata: PageMetadata = Field(description="Page metadata")
    blocks: list[DocBlock] = Field(description="Content blocks")
    related: list[str] = Field(default_factory=list, description="Related page IDs")


# ============================================================================
# Index Models
# ============================================================================


class DocIndex(BaseModel):
    """Documentation index (navigation structure)."""

    version: str = Field(default="1.0", description="Index format version")
    generated_at: str = Field(description="ISO 8601 timestamp")
    navigation: dict[str, str | dict] = Field(
        description="Navigation structure (page_id -> title or nested dict)"
    )

    @classmethod
    def create(cls, navigation: dict[str, str | dict]) -> "DocIndex":
        """Create index with current timestamp."""
        return cls(
            generated_at=datetime.utcnow().isoformat() + "Z",
            navigation=navigation,
        )
