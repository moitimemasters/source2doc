"""Pipeline-graph traversal tests for the docgen registry.

The hierarchical-planner refactor inserts a ``subplan`` phase between
``plan`` and ``write``. This test pins the new event ordering so a
regression that drops ``plan.outline_created`` or ``subplan.completed``
trips the suite — instead of only being noticed when the UI graph
silently disconnects.
"""

from __future__ import annotations

from source2doc.pipelines import DOCGEN
from source2doc.pipelines.types import ENTRY_NODE


def test_subplan_phase_registered() -> None:
    phase_ids = [p.id for p in DOCGEN.phases]
    assert "subplan" in phase_ids
    # Subplan sits between plan and write.
    assert phase_ids.index("plan") < phase_ids.index("subplan") < phase_ids.index("write")


def test_subplan_events_registered() -> None:
    for event_type in ("plan.outline_created", "subplan.requested", "subplan.completed"):
        assert DOCGEN.has_event(event_type), f"missing event {event_type}"
        ev = DOCGEN.event(event_type)
        assert ev.phase in {"plan", "subplan"}


def test_plan_created_lives_in_subplan_phase() -> None:
    """Aggregator emits ``plan.created`` from the subplan phase, so the
    pipeline registry must agree — otherwise the UI graph would draw the
    transition out of the wrong phase.
    """
    assert DOCGEN.event("plan.created").phase == "subplan"


def test_pipeline_path_index_to_write() -> None:
    """Walk the registered transitions from index → … → write and assert
    the new outline + subplan hops are reachable.
    """

    def next_non_loop(source: str, trigger: str) -> str | None:
        for t in DOCGEN.transitions:
            if t.source == source and t.trigger_event == trigger and not t.is_loop:
                return t.target
        return None

    assert next_non_loop(ENTRY_NODE, "generation.requested") == "ingest"
    assert next_non_loop("ingest", "ingest.completed") == "index"
    assert next_non_loop("index", "index.completed") == "plan"
    assert next_non_loop("plan", "plan.outline_created") == "subplan"
    assert next_non_loop("subplan", "plan.created") == "write"


def test_subplan_loop_transitions_present() -> None:
    loops = [
        (t.trigger_event, t.is_loop)
        for t in DOCGEN.transitions
        if t.source == "subplan" and t.target == "subplan"
    ]
    triggers = {trig for trig, is_loop in loops if is_loop}
    assert "subplan.requested" in triggers
    assert "subplan.completed" in triggers


def test_no_direct_plan_to_write_transition() -> None:
    """Old direct ``plan → write`` transition was on ``plan.created``. The
    refactor moves ``plan.created`` to the subplan phase, so the only
    plan-source transition should be ``plan.outline_created → subplan``.
    """
    plan_outs = [t for t in DOCGEN.transitions if t.source == "plan" and not t.is_loop]
    assert len(plan_outs) == 1
    assert plan_outs[0].target == "subplan"
    assert plan_outs[0].trigger_event == "plan.outline_created"
