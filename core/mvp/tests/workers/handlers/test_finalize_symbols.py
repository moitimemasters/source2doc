"""Symbol-extraction heuristic tests for the finalize handler (B6.2 / ТЗ ДОК-08).

The cross-page link index is built from each persisted page's title,
h1/h2 headings, and backticked Python/JS-shaped identifiers in the body.
The heuristic is intentionally simple — these tests pin down the cases
we promise to cover and the cases we deliberately skip (stopwords,
short tokens, non-identifier text).

A follow-up could replace the regex with proper AST extraction; this
test suite is its safety net.
"""

from source2doc.models.docs import (
    CodeBlock,
    DocPage,
    HeadingBlock,
    ListBlock,
    ListItem,
    PageMetadata,
    ParagraphBlock,
)

from docgen_core.workers.handlers.finalize import extract_page_symbols


def _page(blocks: list, title: str = "Documentation Overview") -> DocPage:
    return DocPage(
        title=title,
        summary="Test page",
        metadata=PageMetadata(),
        blocks=blocks,
    )


def test_title_is_recorded_as_page_title() -> None:
    page = _page(blocks=[], title="Architecture")
    symbols = extract_page_symbols(page)
    assert ("Architecture", "page_title") in symbols


def test_h1_h2_headings_recorded_as_page_title_aliases() -> None:
    page = _page(
        title="Index",
        blocks=[
            HeadingBlock(level=1, text="Top Level"),
            HeadingBlock(level=2, text="Sub Section"),
            HeadingBlock(level=3, text="Detail"),
        ],
    )
    symbols = extract_page_symbols(page)
    kinds = dict(symbols)
    assert kinds.get("Top Level") == "page_title"
    assert kinds.get("Sub Section") == "page_title"
    # h3 must NOT be promoted — only h1/h2 are titles.
    assert "Detail" not in kinds


def test_camelcase_in_backticks_classified_as_class() -> None:
    page = _page(blocks=[ParagraphBlock(text="The `DocPage` model wraps a list of `BlockTypes`.")])
    symbols = dict(extract_page_symbols(page))
    assert symbols.get("DocPage") == "class"
    assert symbols.get("BlockTypes") == "class"


def test_snake_case_with_parens_classified_as_function() -> None:
    page = _page(
        blocks=[ParagraphBlock(text="Call `record_page_symbols(...)` after `write_page()`.")]
    )
    symbols = dict(extract_page_symbols(page))
    # Parens are stripped for storage so plain prose mentions also resolve.
    assert symbols.get("record_page_symbols") == "function"
    assert symbols.get("write_page") == "function"


def test_stopwords_and_short_tokens_skipped() -> None:
    page = _page(blocks=[ParagraphBlock(text="See `the` quick `is` short `OK` no.")])
    symbols = dict(extract_page_symbols(page))
    assert "the" not in symbols
    assert "is" not in symbols
    assert "OK" not in symbols  # too short (len 2 — under 3-char minimum).


def test_extraction_recurses_into_lists_and_cuts() -> None:
    page = _page(
        blocks=[
            ListBlock(
                ordered=False,
                items=[
                    ListItem(text="See `MyClass` for the entry point."),
                    ListItem(text="Then call `do_thing()` to start."),
                ],
            ),
        ]
    )
    symbols = dict(extract_page_symbols(page))
    assert symbols.get("MyClass") == "class"
    assert symbols.get("do_thing") == "function"


def test_code_blocks_are_not_scanned() -> None:
    """Code blocks are full <pre>; we only mine inline backticks (one-line
    Markdown spans). A function defined inside a fenced code block must
    not leak into the symbol map."""
    page = _page(
        blocks=[
            CodeBlock(
                lang="python",
                code="def hidden_func():\n    pass\nclass HiddenClass:\n    pass",
            ),
            ParagraphBlock(text="Some unrelated text."),
        ]
    )
    symbols = dict(extract_page_symbols(page))
    assert "hidden_func" not in symbols
    assert "HiddenClass" not in symbols


def test_duplicate_symbols_deduped() -> None:
    page = _page(
        title="DocPage",
        blocks=[
            HeadingBlock(level=1, text="DocPage"),
            HeadingBlock(level=1, text="DocPage"),  # duplicate heading
            ParagraphBlock(text="See `DocPage` and again `DocPage`."),
        ],
    )
    symbols = extract_page_symbols(page)
    # The same (symbol, kind) tuple is collapsed across sources. The handler
    # may legitimately emit ``DocPage`` once per *kind* (page_title from the
    # title/heading and class from the backticked mention), but never twice
    # under the same kind.
    by_kind: dict[str, int] = {}
    for sym, kind in symbols:
        if sym == "DocPage":
            by_kind[kind] = by_kind.get(kind, 0) + 1
    assert by_kind["page_title"] == 1
    # Backtick-derived class entry is fine; case-insensitive lookup on the
    # gateway side prefers ``page_title`` regardless.
    assert all(count == 1 for count in by_kind.values())
