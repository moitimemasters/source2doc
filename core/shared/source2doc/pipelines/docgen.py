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
        id="ingest",
        label="Ingesting Files",
        icon="Download",
        weight=0.18,
        description="Discover files in the source repo and chunk them.",
    ),
    PhaseDef(
        id="index",
        label="Indexing & Embeddings",
        icon="Database",
        weight=0.22,
        description="Embed chunks and write them to the vector store.",
    ),
    PhaseDef(
        id="plan",
        label="Planning Outline",
        icon="ListTree",
        weight=0.05,
        description="Top-planner agent produces the high-level section outline.",
        applies_to_modes=["full"],
    ),
    PhaseDef(
        id="subplan",
        label="Per-Section Planning",
        icon="Layers",
        weight=0.10,
        description="One subplanner agent per section emits page specs scoped to that section.",
        applies_to_modes=["full"],
    ),
    PhaseDef(
        id="write",
        label="Writing Pages",
        icon="PenLine",
        weight=0.20,
        description="Writer agent drafts each page from the plan.",
    ),
    PhaseDef(
        id="diagram",
        label="Generating Diagrams",
        icon="Workflow",
        weight=0.10,
        description="Diagrammer agent fills mermaid placeholders and validates them via mmdc.",
    ),
    PhaseDef(
        id="review",
        label="Reviewing Pages",
        icon="Glasses",
        weight=0.10,
        description="Critic agent reviews each draft for accuracy.",
    ),
    PhaseDef(
        id="evaluate",
        label="Evaluating Reviews",
        icon="Scale",
        weight=0.05,
        description="Decide whether each page is accepted, revised, or rejected.",
    ),
    PhaseDef(
        id="normalize",
        label="Normalizing Blocks",
        icon="Wand2",
        weight=0.05,
        description=(
            "Deterministic block fixes (inline headings, fenced code, dead "
            "diagram placeholders) plus an optional LLM second-pass."
        ),
    ),
    PhaseDef(
        id="finalize",
        label="Finalizing Bundle",
        icon="Package",
        weight=0.10,
        description="Persist pages and close out the generation.",
    ),
    # Iterative-mode short-circuit: when the gateway enqueues with
    # ``mode=incremental``, the index handler emits ``iterative.index_completed``
    # instead of ``index.completed``. The iterative orchestrator handler
    # classifies pages, copies the unchanged ones, marks dead pages
    # deprecated, then re-uses the normal write→review→normalize→finalize
    # pipeline for affected + orphan pages only.
    PhaseDef(
        id="iterative",
        label="Iterative Update",
        icon="GitBranch",
        weight=0.05,
        description=(
            "Classify base-bundle pages against the changed/deleted file "
            "set, copy unchanged pages verbatim, fan out writer rebuilds "
            "for affected + orphan pages."
        ),
        applies_to_modes=["incremental"],
    ),
]


_EVENTS = [
    EventDef(
        type="generation.requested",
        kind=EventKind.TRANSITION,
        phase="ingest",
        label="Generation Requested",
        icon="Rocket",
        summary_template="Generation requested",
        collapsible=False,
    ),
    EventDef(
        type="ingest.started",
        kind=EventKind.PROGRESS,
        phase="ingest",
        label="Ingest Started",
        icon="Play",
        summary_template="Discovered {{files_count}} files",
    ),
    EventDef(
        type="file.ingested",
        kind=EventKind.PROGRESS,
        phase="ingest",
        label="File Ingested",
        icon="FileText",
        summary_template="Ingested {{path}}",
    ),
    EventDef(
        type="chunk.created",
        kind=EventKind.PROGRESS,
        phase="ingest",
        label="Chunk Created",
        icon="Layers",
        summary_template="Chunk {{chunk_id}} from {{path}}",
    ),
    EventDef(
        type="ingest.completed",
        kind=EventKind.TRANSITION,
        phase="ingest",
        label="Ingest Completed",
        icon="CheckCircle2",
        summary_template="Ingested {{chunks_count}} chunks from {{files_count}} files",
        collapsible=False,
    ),
    EventDef(
        type="ingest.failed",
        kind=EventKind.ERROR,
        phase="ingest",
        label="Ingest Failed",
        icon="XCircle",
        summary_template="{{reason}}",
        collapsible=False,
    ),
    EventDef(
        type="index.started",
        kind=EventKind.PROGRESS,
        phase="index",
        label="Indexing Started",
        icon="Play",
        summary_template="Indexing {{chunks_count}} chunks",
    ),
    EventDef(
        type="embeddings.batch",
        kind=EventKind.PROGRESS,
        phase="index",
        label="Embeddings Batch",
        icon="Cpu",
        summary_template="{{processed}}/{{total}} embedded",
    ),
    EventDef(
        type="embeddings.generated",
        kind=EventKind.PROGRESS,
        phase="index",
        label="Embeddings Generated",
        icon="Sparkles",
        summary_template="{{count}} embeddings generated",
    ),
    EventDef(
        type="index.completed",
        kind=EventKind.TRANSITION,
        phase="index",
        label="Indexing Completed",
        icon="CheckCircle2",
        summary_template="Vector index ready",
        collapsible=False,
    ),
    EventDef(
        type="iterative.index_completed",
        kind=EventKind.TRANSITION,
        phase="iterative",
        label="Iterative Index Ready",
        icon="GitBranch",
        summary_template="Vector index ready (iterative mode)",
        collapsible=False,
    ),
    EventDef(
        type="iterative.diff_computed",
        kind=EventKind.PROGRESS,
        phase="iterative",
        label="Diff Computed",
        icon="GitCompare",
        summary_template=(
            "{{from_commit}} → {{to_commit}}: "
            "{{changed_count}} changed, {{deleted_count}} deleted"
        ),
    ),
    EventDef(
        type="iterative.classified",
        kind=EventKind.TRANSITION,
        phase="iterative",
        label="Pages Classified",
        icon="ListChecks",
        summary_template=(
            "{{direct}} direct, {{transitive}} transitive, "
            "{{dead}} deprecated, {{unchanged}} carried"
        ),
        collapsible=False,
    ),
    EventDef(
        type="iterative.page_copied",
        kind=EventKind.PROGRESS,
        phase="iterative",
        label="Page Carried Forward",
        icon="Copy",
        summary_template="{{page_id}} copied from base",
    ),
    EventDef(
        type="iterative.new_files_unmapped",
        kind=EventKind.PROGRESS,
        phase="iterative",
        label="Orphan Files",
        icon="FilePlus",
        summary_template=(
            "{{count}} new file(s) unmapped to existing pages "
            "(orphan planner produced {{specs}} new specs)"
        ),
    ),
    EventDef(
        type="plan.outline_created",
        kind=EventKind.TRANSITION,
        phase="plan",
        label="Plan Outline",
        icon="ListChecks",
        summary_template="{{section_count}} sections drafted",
        collapsible=False,
    ),
    EventDef(
        type="subplan.requested",
        kind=EventKind.TRANSITION,
        phase="subplan",
        label="Subplan Requested",
        icon="Layers",
        summary_template="{{section_id}}",
    ),
    EventDef(
        type="subplan.completed",
        kind=EventKind.TRANSITION,
        phase="subplan",
        label="Subplan Done",
        icon="CheckCircle2",
        summary_template="{{section_id}}: {{pages_count}} pages",
    ),
    EventDef(
        type="plan.created",
        kind=EventKind.TRANSITION,
        phase="subplan",
        label="Plan Created",
        icon="ListChecks",
        summary_template="Plan with {{pages_count}} pages",
        collapsible=False,
    ),
    EventDef(
        type="doc.index.created",
        kind=EventKind.PROGRESS,
        phase="subplan",
        label="Bundle Initialized",
        icon="FolderPlus",
        summary_template="Bundle {{bundle_id}} created",
    ),
    EventDef(
        type="page.write_requested",
        kind=EventKind.TRANSITION,
        phase="write",
        label="Page Write Requested",
        icon="PenLine",
        summary_template="Writing {{page_spec.page_id}} (attempt {{attempt}})",
    ),
    EventDef(
        type="page.written",
        kind=EventKind.TRANSITION,
        phase="write",
        label="Page Written",
        icon="FileCheck",
        summary_template="{{page_id}} drafted",
    ),
    EventDef(
        type="page.failed",
        kind=EventKind.ERROR,
        phase="write",
        label="Page Failed",
        icon="FileX",
        summary_template="{{page_id}}: {{error}}",
        collapsible=False,
    ),
    EventDef(
        type="diagram.requested",
        kind=EventKind.TRANSITION,
        phase="diagram",
        label="Diagram Requested",
        icon="Workflow",
        summary_template="{{page_id}}/{{placeholder_id}} ({{kind}})",
    ),
    EventDef(
        type="diagram.completed",
        kind=EventKind.TRANSITION,
        phase="diagram",
        label="Diagram Completed",
        icon="CheckCircle2",
        summary_template="{{page_id}}/{{placeholder_id}} {{status}}",
    ),
    EventDef(
        type="page.diagrams_completed",
        kind=EventKind.TRANSITION,
        phase="diagram",
        label="Page Diagrams Done",
        icon="CheckCheck",
        summary_template="{{page_id}}: {{succeeded}}/{{total}} diagrams",
    ),
    EventDef(
        type="page.reviewed",
        kind=EventKind.TRANSITION,
        phase="review",
        label="Page Reviewed",
        icon="ClipboardCheck",
        summary_template="{{page_id}} reviewed",
    ),
    EventDef(
        type="page.revision_requested",
        kind=EventKind.TRANSITION,
        phase="evaluate",
        label="Revision Requested",
        icon="RotateCcw",
        summary_template="{{page_id}} revising (attempt {{attempt}})",
    ),
    EventDef(
        type="page.completed",
        kind=EventKind.TRANSITION,
        phase="evaluate",
        label="Page Accepted",
        icon="CheckCircle",
        summary_template="{{page_id}} accepted",
    ),
    EventDef(
        type="page.normalize_started",
        kind=EventKind.TRANSITION,
        phase="normalize",
        label="Normalize Started",
        icon="Wand2",
        summary_template="Normalizing {{page_id}}",
    ),
    EventDef(
        type="page.normalized",
        kind=EventKind.TRANSITION,
        phase="normalize",
        label="Page Normalized",
        icon="Wand2",
        summary_template="{{page_id}} normalized ({{deterministic_edits}} fixes, llm={{llm_used}})",
    ),
    EventDef(
        type="doc.page.created",
        kind=EventKind.PROGRESS,
        phase="finalize",
        label="Page Saved",
        icon="Save",
        summary_template="{{page_id}} saved (score {{score}})",
    ),
    EventDef(
        type="doc.page.failed",
        kind=EventKind.ERROR,
        phase="finalize",
        label="Page Discarded",
        icon="FileX",
        summary_template="{{page_id}}: {{error}}",
        collapsible=False,
    ),
    EventDef(
        type="generation.completed",
        kind=EventKind.TERMINAL,
        phase="finalize",
        label="Generation Completed",
        icon="PartyPopper",
        summary_template="Generation done — {{pages_count}} pages",
        collapsible=False,
    ),
    EventDef(
        type="step.failed",
        kind=EventKind.ERROR,
        phase="finalize",
        label="Step Failed",
        icon="AlertOctagon",
        summary_template="{{step}}: {{error}}",
        collapsible=False,
    ),
    EventDef(
        type="task.failed",
        kind=EventKind.ERROR,
        phase="finalize",
        label="Task Failed",
        icon="AlertTriangle",
        summary_template="{{event_type}}: {{error}}",
        collapsible=False,
    ),
    EventDef(
        type="task.stopped",
        kind=EventKind.TERMINAL,
        phase="finalize",
        label="Stopped by User",
        icon="StopCircle",
        summary_template="Cancelled — {{reason}}",
        collapsible=False,
    ),
    EventDef(
        type="task.resumed",
        kind=EventKind.PROGRESS,
        phase="finalize",
        label="Resumed After Failure",
        icon="PlayCircle",
        summary_template=(
            "Resumed from {{resumed_from_event_type}} "
            "(prior failure preserved as audit entry)"
        ),
        collapsible=False,
    ),
    EventDef(
        type="handler.error",
        kind=EventKind.ERROR,
        phase="finalize",
        label="Handler Error",
        icon="AlertTriangle",
        summary_template="{{failed_event_type}}: {{error}}",
        collapsible=False,
    ),
]


_TRANSITIONS = [
    TransitionDef(source=ENTRY_NODE, target="ingest", trigger_event="generation.requested"),
    TransitionDef(source="ingest", target="index", trigger_event="ingest.completed"),
    TransitionDef(source="index", target="plan", trigger_event="index.completed"),
    TransitionDef(
        source="index", target="iterative", trigger_event="iterative.index_completed"
    ),
    TransitionDef(
        source="iterative",
        target="iterative",
        trigger_event="iterative.diff_computed",
        is_loop=True,
    ),
    TransitionDef(
        source="iterative",
        target="iterative",
        trigger_event="iterative.classified",
        is_loop=True,
    ),
    TransitionDef(
        source="iterative",
        target="iterative",
        trigger_event="iterative.page_copied",
        is_loop=True,
    ),
    TransitionDef(
        source="iterative",
        target="iterative",
        trigger_event="iterative.new_files_unmapped",
        is_loop=True,
    ),
    TransitionDef(
        source="iterative",
        target="write",
        trigger_event="page.write_requested",
    ),
    TransitionDef(source="plan", target="subplan", trigger_event="plan.outline_created"),
    TransitionDef(
        source="subplan",
        target="subplan",
        trigger_event="subplan.requested",
        is_loop=True,
    ),
    TransitionDef(
        source="subplan",
        target="subplan",
        trigger_event="subplan.completed",
        is_loop=True,
    ),
    TransitionDef(source="subplan", target="write", trigger_event="plan.created"),
    TransitionDef(
        source="write", target="write", trigger_event="page.write_requested", is_loop=True
    ),
    TransitionDef(source="write", target="diagram", trigger_event="page.written"),
    TransitionDef(
        source="diagram",
        target="diagram",
        trigger_event="diagram.requested",
        is_loop=True,
    ),
    TransitionDef(
        source="diagram",
        target="diagram",
        trigger_event="diagram.completed",
        is_loop=True,
    ),
    TransitionDef(
        source="diagram",
        target="review",
        trigger_event="page.diagrams_completed",
    ),
    TransitionDef(source="review", target="evaluate", trigger_event="page.reviewed"),
    TransitionDef(source="review", target="normalize", trigger_event="page.completed"),
    TransitionDef(
        source="evaluate", target="write", trigger_event="page.revision_requested", is_loop=True
    ),
    TransitionDef(source="evaluate", target="normalize", trigger_event="page.completed"),
    TransitionDef(
        source="normalize",
        target="normalize",
        trigger_event="page.normalize_started",
        is_loop=True,
    ),
    TransitionDef(source="normalize", target="finalize", trigger_event="page.normalized"),
    TransitionDef(source="finalize", target=TERMINAL_OK_NODE, trigger_event="generation.completed"),
    TransitionDef(
        source="ingest",
        target=TERMINAL_FAIL_NODE,
        trigger_event="ingest.failed",
        is_failure=True,
    ),
    TransitionDef(
        source="finalize",
        target=TERMINAL_FAIL_NODE,
        trigger_event="task.failed",
        is_failure=True,
    ),
    TransitionDef(
        source="finalize",
        target=TERMINAL_FAIL_NODE,
        trigger_event="handler.error",
        is_failure=True,
    ),
]


DOCGEN = Pipeline(
    id="docgen",
    label="Documentation Generation",
    entry_event="generation.requested",
    terminal_events=["generation.completed", "task.failed"],
    phases=_PHASES,
    events=_EVENTS,
    transitions=_TRANSITIONS,
)
