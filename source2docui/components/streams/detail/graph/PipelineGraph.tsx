"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
    Background,
    Controls,
    MarkerType,
    ReactFlow,
    ReactFlowProvider,
    useNodesInitialized,
    useReactFlow,
    type Edge,
    type Node,
    type NodeMouseHandler,
    type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { StreamEvent } from "@/lib/gateway/types";
import { usePipelineGraph } from "@/lib/pipelines/usePipelineGraph";
import { getEventDef, type Pipeline } from "@/lib/pipelines/schema";
import { PhaseNode } from "./PhaseNode";
import { PhaseDrawer } from "./PhaseDrawer";
import { layoutGraph, NODE_HEIGHT, NODE_WIDTH } from "./layout";

interface PipelineGraphProps {
    pipelineId: string;
    events: StreamEvent[];
    height?: number;
    showFailureEdges?: boolean;
}

const NODE_TYPES: NodeTypes = { phase: PhaseNode };

function shortLabel(eventType: string, fallback: string): string {
    // Use the post-dot suffix as a compact label so it fits on the edge
    // ("page.completed" -> "completed", "page.write_requested" -> "write requested").
    const last = eventType.split(".").pop() || eventType;
    const cleaned = last.replace(/_/g, " ");
    return cleaned || fallback;
}

function buildEdges(
    pipeline: Pipeline,
    activePhase: string | null,
    showFailureEdges: boolean,
    visiblePhaseIds: Set<string>,
): Edge[] {
    return pipeline.transitions
        .filter((t) => {
            if (t.source === "_entry_") return false;
            if (t.target === "_terminal_ok_" || t.target === "_terminal_fail_")
                return false;
            if (t.is_failure && !showFailureEdges) return false;
            // Drop transitions to/from phases the run-mode filter hid.
            // Without this dagre auto-creates phantom nodes for the
            // missing endpoints, which it then ranks alongside the real
            // ones — pushing the surviving phases to lower rows.
            if (!visiblePhaseIds.has(t.source)) return false;
            if (!visiblePhaseIds.has(t.target)) return false;
            return true;
        })
        .map((t) => {
            const isLoop = t.is_loop;
            const isActiveTarget = activePhase === t.target;
            const def = getEventDef(pipeline, t.trigger_event);
            const fullLabel = def?.label ?? t.trigger_event;
            const label = shortLabel(t.trigger_event, fullLabel);
            return {
                id: `${t.source}->${t.target}:${t.trigger_event}`,
                source: t.source,
                target: t.target,
                // Loop edges leave from the bottom and re-enter from the bottom
                // so they swing under the row without crossing intermediate nodes.
                sourceHandle: isLoop ? "bottom-source" : "right",
                targetHandle: isLoop ? "bottom-target" : "left",
                type: "smoothstep",
                pathOptions: isLoop ? { borderRadius: 24 } : undefined,
                animated: isActiveTarget && !isLoop,
                label,
                labelStyle: {
                    fontSize: 11,
                    fontWeight: 500,
                    fill: "var(--foreground)",
                },
                labelShowBg: true,
                labelBgStyle: {
                    fill: "var(--background)",
                    fillOpacity: 0.95,
                    stroke: "var(--border)",
                },
                labelBgPadding: [8, 4] as [number, number],
                labelBgBorderRadius: 4,
                style: {
                    stroke: t.is_failure
                        ? "var(--destructive)"
                        : isLoop
                          ? "var(--muted-foreground)"
                          : "var(--foreground)",
                    strokeWidth: isActiveTarget ? 2.5 : 1.5,
                    strokeDasharray: isLoop ? "6 4" : undefined,
                },
                markerEnd: {
                    type: MarkerType.ArrowClosed,
                    color: t.is_failure
                        ? "var(--destructive)"
                        : "var(--foreground)",
                },
                data: { isLoop, isFailure: t.is_failure, fullLabel },
            };
        });
}

function PipelineGraphInner({
    pipeline,
    phases,
    activePhase,
    showFailureEdges,
    eventsByPhase,
    height,
}: {
    pipeline: Pipeline;
    phases: ReturnType<typeof usePipelineGraph>["phases"];
    activePhase: string | null;
    showFailureEdges: boolean;
    eventsByPhase: ReturnType<typeof usePipelineGraph>["eventsByPhase"];
    height: number;
}) {
    const [openPhaseId, setOpenPhaseId] = useState<string | null>(null);
    const [nodes, setNodes] = useState<Node[]>([]);
    const [edges, setEdges] = useState<Edge[]>([]);

    const nodesInitialized = useNodesInitialized();
    const { getNodes, fitView } = useReactFlow();

    const onNodeClick = useCallback<NodeMouseHandler>((_, node) => {
        setOpenPhaseId(node.id);
    }, []);

    // Initial render: nodes at (0,0) with default placeholder size so React Flow
    // mounts and measures real CSS dimensions.
    useEffect(() => {
        const visiblePhaseIds = new Set(phases.map((p) => p.phase.id));
        const initialNodes: Node[] = phases.map((state) => ({
            id: state.phase.id,
            type: "phase",
            position: { x: 0, y: 0 },
            data: { ...state },
        }));
        const initialEdges = buildEdges(
            pipeline,
            activePhase,
            showFailureEdges,
            visiblePhaseIds,
        );
        const laidOut = layoutGraph(initialNodes, initialEdges);
        setNodes(laidOut.nodes);
        setEdges(laidOut.edges);
    }, [pipeline, phases, activePhase, showFailureEdges]);

    // After React Flow measures the rendered nodes, re-layout using actual
    // sizes so nothing is truncated and edges route around real bounds.
    useEffect(() => {
        if (!nodesInitialized) return;
        const measured = getNodes();
        if (measured.length === 0) return;

        const sized = measured.map((n) => ({
            ...n,
            width: n.measured?.width ?? (n.width as number | undefined) ?? NODE_WIDTH,
            height:
                n.measured?.height ?? (n.height as number | undefined) ?? NODE_HEIGHT,
        }));
        const laidOut = layoutGraph(sized, edges);
        setNodes(laidOut.nodes);
        // Fit on the next frame after React commits the new positions.
        // Two RAFs because xyflow recomputes its internal viewport on the
        // next frame after we set state.
        requestAnimationFrame(() => {
            requestAnimationFrame(() =>
                fitView({ padding: 0.08, maxZoom: 1.1, minZoom: 0.4 }),
            );
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nodesInitialized, phases.length]);

    const openPhaseState = useMemo(
        () => (openPhaseId ? phases.find((p) => p.phase.id === openPhaseId) : null),
        [openPhaseId, phases],
    );

    return (
        <>
            <div
                className="rounded-lg border border-border bg-muted/30"
                style={{ height }}
            >
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    nodeTypes={NODE_TYPES}
                    onNodeClick={onNodeClick}
                    fitView
                    fitViewOptions={{ padding: 0.08, maxZoom: 1.1, minZoom: 0.4 }}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    elementsSelectable={false}
                    proOptions={{ hideAttribution: true }}
                    minZoom={0.3}
                    maxZoom={2}
                >
                    <Background gap={16} />
                    <Controls showInteractive={false} />
                </ReactFlow>
            </div>
            <PhaseDrawer
                open={openPhaseId !== null}
                onOpenChange={(o) => !o && setOpenPhaseId(null)}
                phaseState={openPhaseState ?? null}
                pipeline={pipeline}
                events={openPhaseId ? (eventsByPhase[openPhaseId] ?? []) : []}
            />
        </>
    );
}

export function PipelineGraph({
    pipelineId,
    events,
    height = 480,
    showFailureEdges = false,
}: PipelineGraphProps) {
    const { pipeline, loading, error, phases, activePhase, eventsByPhase } =
        usePipelineGraph(pipelineId, events);

    if (loading && !pipeline) {
        return (
            <div
                className="rounded-lg border border-border bg-card flex items-center justify-center text-sm text-muted-foreground"
                style={{ height }}
            >
                Loading pipeline schema…
            </div>
        );
    }

    if (error) {
        return (
            <div
                className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
                style={{ height }}
            >
                Failed to load pipeline schema: {error}
            </div>
        );
    }

    if (!pipeline) return null;

    return (
        <ReactFlowProvider>
            <PipelineGraphInner
                pipeline={pipeline}
                phases={phases}
                activePhase={activePhase}
                showFailureEdges={showFailureEdges}
                eventsByPhase={eventsByPhase}
                height={height}
            />
        </ReactFlowProvider>
    );
}
