"""B9.3 — codetour failure-payload builder must surface
``reason='llm_timeout'`` for ``LLMTimeoutError``.

Mirror of the docgen-side test in ``core/mvp/tests/workers/test_timeout_event.py``
but exercises the codetour processor's payload helper, which is the
equivalent dispatch-loop logic for the codetour pipeline.
"""

from __future__ import annotations

from uuid import uuid4

from source2doc.errors import LLMTimeoutError

from worker.codetour.processor import _build_failure_payload


def test_llm_timeout_payload_has_reason_field() -> None:
    tour_id = uuid4()
    exc = LLMTimeoutError(
        model="claude-haiku-4-5-20251001",
        elapsed_s=120.7,
        last_attempt_n=3,
    )

    payload = _build_failure_payload(tour_id, exc)

    assert payload["tour_id"] == str(tour_id)
    assert payload["error_type"] == "LLMTimeoutError"
    assert payload["reason"] == "llm_timeout"
    assert payload["model"] == "claude-haiku-4-5-20251001"
    assert payload["elapsed_s"] == 120.7
    assert payload["last_attempt_n"] == 3
    assert payload["retry_after"] is None
    assert "timed out" in payload["error_message"].lower()


def test_generic_failure_payload_has_no_reason() -> None:
    """Existing event consumers must not see a ``reason`` key for
    non-timeout errors — that field is reserved for known structured
    failure modes."""

    tour_id = uuid4()
    payload = _build_failure_payload(tour_id, ValueError("bad input"))

    assert "reason" not in payload
    assert payload["error_type"] == "ValueError"
    assert payload["tour_id"] == str(tour_id)
