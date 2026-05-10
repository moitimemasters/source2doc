"""Mermaid diagram kinds + minimal valid skeletons for the diagrammer prompt."""

from typing import Literal


MermaidKind = Literal[
    "flowchart",
    "sequence",
    "class",
    "er",
    "state",
    "gantt",
    "pie",
    "journey",
    "mindmap",
    "gitGraph",
    "c4",
]


ALL_KINDS: tuple[MermaidKind, ...] = (
    "flowchart",
    "sequence",
    "class",
    "er",
    "state",
    "gantt",
    "pie",
    "journey",
    "mindmap",
    "gitGraph",
    "c4",
)


KIND_HINTS: dict[MermaidKind, str] = {
    "flowchart": "flowchart TD\n    A[Start] --> B[End]",
    "sequence": "sequenceDiagram\n    Alice->>Bob: Hello",
    "class": "classDiagram\n    class Foo {\n        +bar() void\n    }",
    "er": "erDiagram\n    USER ||--o{ ORDER : places",
    "state": "stateDiagram-v2\n    [*] --> Idle\n    Idle --> Done",
    "gantt": "gantt\n    title Demo\n    section A\n    Task :a1, 2026-01-01, 1d",
    "pie": 'pie\n    title Demo\n    "A" : 50\n    "B" : 50',
    "journey": "journey\n    title Demo\n    section A\n      Step: 5: User",
    "mindmap": "mindmap\n  root((Root))\n    A\n    B",
    "gitGraph": "gitGraph\n    commit\n    branch dev\n    commit",
    "c4": (
        'C4Context\n    Person(user, "User")\n    System(sys, "System")\n    Rel(user, sys, "uses")'
    ),
}
