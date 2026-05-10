"""Block-level normalization for writer outputs.

The normalizer fixes structural drift introduced by weaker writers:
literal ``## Header`` markdown inside paragraph text, fenced code blocks
embedded in paragraphs, dead ``mermaid_placeholder`` blocks left over
after the diagram phase, and heading-level skips. Pure functions live in
:mod:`source2doc.normalizer.blocks`; the worker handler that drives the
phase is in ``docgen_core.workers.handlers.normalize``.
"""

from source2doc.normalizer.blocks import (
    NormalizationReport,
    normalize_blocks,
)


__all__ = ["NormalizationReport", "normalize_blocks"]
