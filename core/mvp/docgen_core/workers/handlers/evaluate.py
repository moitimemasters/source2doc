import dataclasses as dc
import typing as tp

from source2doc import config
from source2doc.logging import get_logger
from source2doc.models import review as review_models

from docgen_core.workers import context as ctx_mod
from docgen_core.workers import env as env_mod


logger = get_logger(__name__)


@dc.dataclass
class ReviewDecision:
    needs_revision: bool
    reason: str


async def handle(
    env: env_mod.DocGenEnv,
    ctx: ctx_mod.GenerationContext,
    data: dict[str, tp.Any],
) -> None:
    generation_id = data["generation_id"]
    page_id = data["page_id"]
    page_data = data["page"]
    page_spec = data["page_spec"]
    review_data = data["review"]
    attempt = data["attempt"]

    review = review_models.CriticOutput(**review_data)

    logger.info(
        "page_reviewed",
        page_id=page_id,
        score=review.score,
        has_hallucinations=review.has_hallucinations,
        attempt=attempt,
    )

    decision = decide(review, attempt, env.config.generation)

    if decision.needs_revision:
        logger.info(
            "page_revision_requested",
            page_id=page_id,
            score=review.score,
            reason=decision.reason,
            attempt=attempt,
        )
        await _emit_revision_requested(
            env, generation_id, page_id, page_spec, page_data, review_data, data, attempt
        )
    else:
        await _emit_page_completed(env, generation_id, page_id, page_data, review)


def decide(
    review: review_models.CriticOutput,
    attempt: int,
    config: config.GenerationConfig,
) -> ReviewDecision:
    # Global ceiling regardless of which path keeps requesting revisions.
    # Stops a critic that keeps flipping between has_hallucinations and
    # low_score from looping past the per-reason caps.
    if attempt >= config.max_total_attempts:
        return ReviewDecision(
            needs_revision=False,
            reason="max_total_attempts_reached",
        )

    if review.has_hallucinations:
        if attempt < config.max_hallucination_retries:
            return ReviewDecision(needs_revision=True, reason="hallucinations_detected")
        return ReviewDecision(needs_revision=False, reason="max_hallucination_retries_reached")

    if review.score < config.min_page_score:
        if attempt < config.max_page_retries:
            return ReviewDecision(needs_revision=True, reason="low_score")
        return ReviewDecision(needs_revision=False, reason="max_retries_reached")

    return ReviewDecision(needs_revision=False, reason="accepted")


async def _emit_revision_requested(
    env: env_mod.DocGenEnv,
    generation_id: str,
    page_id: str,
    page_spec: dict,
    page_data: dict,
    review_data: dict,
    data: dict[str, tp.Any],
    attempt: int,
) -> None:
    await env.event_bus.emit(
        "page.revision_requested",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "page_spec": page_spec,
            "previous_page": page_data,
            "previous_review": review_data,
            "repo_id": data.get("repo_id"),
            "path": data.get("path"),
            "attempt": attempt + 1,
        },
    )


async def _emit_page_completed(
    env: env_mod.DocGenEnv,
    generation_id: str,
    page_id: str,
    page_data: dict,
    review: review_models.CriticOutput,
) -> None:
    await env.event_bus.emit(
        "page.completed",
        {
            "generation_id": generation_id,
            "page_id": page_id,
            "page": page_data,
            "final_score": review.score,
            "review_summary": review.summary,
        },
    )
