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
        label="Generating Tour",
        icon="Map",
        weight=0.7,
        description="Walk the repo and add tour steps.",
    ),
    PhaseDef(
        id="followup",
        label="Followup Update",
        icon="RefreshCw",
        weight=0.3,
        description="Apply a follow-up regeneration to an existing tour.",
    ),
]


_EVENTS = [
    EventDef(
        type="codetour.started",
        kind=EventKind.TRANSITION,
        phase="running",
        label="Tour Started",
        icon="Rocket",
        summary_template="Generating tour {{tour_id}}",
        collapsible=False,
    ),
    EventDef(
        type="codetour.step_added",
        kind=EventKind.PROGRESS,
        phase="running",
        label="Step Added",
        icon="Plus",
        summary_template="Step {{step_index}}: {{title}}",
    ),
    EventDef(
        type="codetour.step_rejected",
        kind=EventKind.PROGRESS,
        phase="running",
        label="Step Rejected",
        icon="XCircle",
        summary_template="Step rejected: {{reason}}",
    ),
    EventDef(
        type="codetour.step_line_drift",
        kind=EventKind.PROGRESS,
        phase="running",
        label="Line Drift Adjusted",
        icon="MoveVertical",
        summary_template="{{path}}: line {{from_line}} → {{to_line}}",
    ),
    EventDef(
        type="codetour.completed",
        kind=EventKind.TERMINAL,
        phase="running",
        label="Tour Completed",
        icon="PartyPopper",
        summary_template="Tour ready ({{steps_count}} steps)",
        collapsible=False,
    ),
    EventDef(
        type="codetour.failed",
        kind=EventKind.ERROR,
        phase="running",
        label="Tour Failed",
        icon="AlertOctagon",
        summary_template="{{error}}",
        collapsible=False,
    ),
    EventDef(
        type="codetour.followup_started",
        kind=EventKind.TRANSITION,
        phase="followup",
        label="Followup Started",
        icon="RefreshCw",
        summary_template="Followup for tour {{tour_id}}",
        collapsible=False,
    ),
    EventDef(
        type="codetour.followup_step_added",
        kind=EventKind.PROGRESS,
        phase="followup",
        label="Followup Step Added",
        icon="Plus",
        summary_template="Step {{step_index}}: {{title}}",
    ),
    EventDef(
        type="codetour.followup_step_rejected",
        kind=EventKind.PROGRESS,
        phase="followup",
        label="Followup Step Rejected",
        icon="XCircle",
        summary_template="Step rejected: {{reason}}",
    ),
    EventDef(
        type="codetour.followup_completed",
        kind=EventKind.TERMINAL,
        phase="followup",
        label="Followup Completed",
        icon="CheckCircle2",
        summary_template="Followup applied",
        collapsible=False,
    ),
    EventDef(
        type="codetour.followup_failed",
        kind=EventKind.ERROR,
        phase="followup",
        label="Followup Failed",
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
    EventDef(
        type="handler.error",
        kind=EventKind.ERROR,
        phase="running",
        label="Handler Error",
        icon="AlertTriangle",
        summary_template="{{failed_event_type}}: {{error}}",
        collapsible=False,
    ),
]


_TRANSITIONS = [
    TransitionDef(source=ENTRY_NODE, target="running", trigger_event="codetour.started"),
    TransitionDef(source=ENTRY_NODE, target="followup", trigger_event="codetour.followup_started"),
    TransitionDef(source="running", target=TERMINAL_OK_NODE, trigger_event="codetour.completed"),
    TransitionDef(
        source="followup", target=TERMINAL_OK_NODE, trigger_event="codetour.followup_completed"
    ),
    TransitionDef(
        source="running",
        target=TERMINAL_FAIL_NODE,
        trigger_event="codetour.failed",
        is_failure=True,
    ),
    TransitionDef(
        source="followup",
        target=TERMINAL_FAIL_NODE,
        trigger_event="codetour.followup_failed",
        is_failure=True,
    ),
    TransitionDef(
        source="running",
        target=TERMINAL_FAIL_NODE,
        trigger_event="task.failed",
        is_failure=True,
    ),
    TransitionDef(
        source="running",
        target=TERMINAL_FAIL_NODE,
        trigger_event="handler.error",
        is_failure=True,
    ),
]


CODETOUR = Pipeline(
    id="codetour",
    label="Code Tour Generation",
    entry_event="codetour.started",
    terminal_events=[
        "codetour.completed",
        "codetour.followup_completed",
        "codetour.failed",
        "codetour.followup_failed",
    ],
    phases=_PHASES,
    events=_EVENTS,
    transitions=_TRANSITIONS,
)
