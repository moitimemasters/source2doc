"""Pure-logic tests for the page review decision branch.

PMI-mapping (osokin): page-revision loop in chapter 6 — the Critic agent
returns a score / hallucinations flag, and this function decides whether
to re-run the Writer or accept the page. All branches must be covered:

  * hallucinations + retry budget left  → revise
  * hallucinations + budget exhausted   → accept (fall back, log only)
  * low score + retry budget left       → revise
  * low score + budget exhausted        → accept
  * acceptable score + no hallucinations → accept
"""

import pytest

from source2doc.config import GenerationConfig
from source2doc.models.review import CriticOutput, Issue

from docgen_core.workers.handlers.evaluate import decide


def _config(**overrides) -> GenerationConfig:
    return GenerationConfig(
        min_page_score=overrides.get("min_page_score", 7),
        max_page_retries=overrides.get("max_page_retries", 2),
        max_hallucination_retries=overrides.get("max_hallucination_retries", 3),
    )


def _review(score: int, hallucinations: bool, issues: list[Issue] | None = None) -> CriticOutput:
    return CriticOutput(
        score=score,
        has_hallucinations=hallucinations,
        issues=issues or [],
        suggestions=[],
        summary="ok",
    )


def test_high_score_no_hallucinations_accepted() -> None:
    decision = decide(_review(score=9, hallucinations=False), attempt=1, config=_config())
    assert decision.needs_revision is False
    assert decision.reason == "accepted"


def test_low_score_with_budget_left_triggers_revision() -> None:
    decision = decide(_review(score=4, hallucinations=False), attempt=1, config=_config())
    assert decision.needs_revision is True
    assert decision.reason == "low_score"


def test_low_score_with_budget_exhausted_accepts_anyway() -> None:
    # max_page_retries=2 means attempts 1 and 2 may revise; attempt 2 is the
    # last one allowed. attempt 2 -> 2 < 2 is False, so fall through.
    decision = decide(_review(score=4, hallucinations=False), attempt=2, config=_config())
    assert decision.needs_revision is False
    assert decision.reason == "max_retries_reached"


def test_hallucination_takes_precedence_over_score() -> None:
    """Even if the score is acceptable, hallucinations must trigger revision
    until the hallucination retry budget is exhausted."""
    decision = decide(_review(score=10, hallucinations=True), attempt=1, config=_config())
    assert decision.needs_revision is True
    assert decision.reason == "hallucinations_detected"


def test_hallucination_budget_exhausted_falls_back_to_accept() -> None:
    decision = decide(_review(score=10, hallucinations=True), attempt=3, config=_config())
    assert decision.needs_revision is False
    assert decision.reason == "max_hallucination_retries_reached"


@pytest.mark.parametrize("score,attempt,want_revise", [
    (10, 1, False),
    (7, 1, False),     # >= min_page_score
    (6, 1, True),      # below threshold
    (6, 2, False),     # threshold met but no budget
])
def test_score_threshold_boundary(score: int, attempt: int, want_revise: bool) -> None:
    decision = decide(_review(score=score, hallucinations=False), attempt=attempt, config=_config())
    assert decision.needs_revision is want_revise
