from enum import StrEnum

from pydantic import BaseModel, Field


ENTRY_NODE = "_entry_"
TERMINAL_OK_NODE = "_terminal_ok_"
TERMINAL_FAIL_NODE = "_terminal_fail_"


class EventKind(StrEnum):
    TRANSITION = "transition"
    PROGRESS = "progress"
    LOG = "log"
    ERROR = "error"
    TERMINAL = "terminal"


class EventDef(BaseModel):
    type: str
    kind: EventKind
    phase: str
    label: str
    icon: str = "Activity"
    summary_template: str | None = None
    color: str | None = None
    collapsible: bool = True


class PhaseDef(BaseModel):
    id: str
    label: str
    icon: str = "Circle"
    weight: float = 1.0
    description: str | None = None
    # Pipeline branches that include this phase. Empty list means "shown
    # for every mode" (default for backwards compat). The docgen pipeline
    # uses this to hide planner phases on iterative runs and the
    # iterative orchestration phase on full-mode runs — otherwise the
    # unused branch hangs in the graph as a permanently-idle node. The
    # active mode is derived UI-side from the events that actually fired.
    applies_to_modes: list[str] = Field(default_factory=list)


class TransitionDef(BaseModel):
    source: str
    target: str
    trigger_event: str
    is_loop: bool = False
    is_failure: bool = False


class Pipeline(BaseModel):
    id: str
    label: str
    entry_event: str
    terminal_events: list[str] = Field(default_factory=list)
    phases: list[PhaseDef]
    events: list[EventDef]
    transitions: list[TransitionDef]

    def event(self, event_type: str) -> EventDef:
        for ev in self.events:
            if ev.type == event_type:
                return ev
        raise KeyError(f"event {event_type!r} not in pipeline {self.id!r}")

    def has_event(self, event_type: str) -> bool:
        return any(ev.type == event_type for ev in self.events)

    def phase(self, phase_id: str) -> PhaseDef:
        for ph in self.phases:
            if ph.id == phase_id:
                return ph
        raise KeyError(f"phase {phase_id!r} not in pipeline {self.id!r}")

    def phase_for_event(self, event_type: str) -> str | None:
        if self.has_event(event_type):
            return self.event(event_type).phase
        return None

    def transitions_for(self, event_type: str) -> list[TransitionDef]:
        return [t for t in self.transitions if t.trigger_event == event_type]

    def target_phase_for_event(self, event_type: str) -> str | None:
        for t in self.transitions:
            if t.trigger_event == event_type and not t.is_loop:
                return t.target
        return None
