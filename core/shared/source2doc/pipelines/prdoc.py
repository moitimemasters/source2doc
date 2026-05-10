"""Pipeline registry for PR microdoc generation (closes ТЗ ИНТ-02 / ГЕН-06).

A short, single-phase pipeline: one task per request. The ``running`` phase
covers RAG search + LLM agent run + storage write.
"""

from source2doc.pipelines.types import (
    ENTRY_NODE,
    TERMINAL_FAIL_NODE,
    TERMINAL_OK_NODE,
    EventDef,
    EventKind,
    PhaseDef,
    Pipeline,
    TransitionDef,
)


_PHASES = [
    PhaseDef(
        id="running",
        label="Generating PR Doc",
        icon="GitPullRequest",
        weight=1.0,
        description="Summarize the PR diff and write to storage.",
    ),
]


_EVENTS = [
    EventDef(
        type="prdoc.requested",
        kind=EventKind.TRANSITION,
        phase="running",
        label="PR Doc Requested",
        icon="Inbox",
        summary_template="Requested for {{generation_id}}",
        collapsible=False,
    ),
    EventDef(
        type="prdoc.running",
        kind=EventKind.TRANSITION,
        phase="running",
        label="PR Doc Running",
        icon="Loader",
        summary_template="Summarizing {{files_changed}} files",
        collapsible=False,
    ),
    EventDef(
        type="prdoc.completed",
        kind=EventKind.TERMINAL,
        phase="running",
        label="PR Doc Completed",
        icon="CheckCircle2",
        summary_template="Summary ready ({{files_summarised}} files)",
        collapsible=False,
    ),
    EventDef(
        type="prdoc.failed",
        kind=EventKind.ERROR,
        phase="running",
        label="PR Doc Failed",
        icon="AlertOctagon",
        summary_template="{{error}}",
        collapsible=False,
    ),
    EventDef(
        type="task.failed",
        kind=EventKind.ERROR,
        phase="running",
        label="Task Failed",
        icon="AlertTriangle",
        summary_template="{{event_type}}: {{error}}",
        collapsible=False,
    ),
]


_TRANSITIONS = [
    TransitionDef(source=ENTRY_NODE, target="running", trigger_event="prdoc.requested"),
    TransitionDef(source="running", target=TERMINAL_OK_NODE, trigger_event="prdoc.completed"),
    TransitionDef(
        source="running",
        target=TERMINAL_FAIL_NODE,
        trigger_event="prdoc.failed",
        is_failure=True,
    ),
    TransitionDef(
        source="running",
        target=TERMINAL_FAIL_NODE,
        trigger_event="task.failed",
        is_failure=True,
    ),
]


PRDOC = Pipeline(
    id="prdoc",
    label="PR Microdoc Generation",
    entry_event="prdoc.requested",
    terminal_events=["prdoc.completed", "prdoc.failed"],
    phases=_PHASES,
    events=_EVENTS,
    transitions=_TRANSITIONS,
)
