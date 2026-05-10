import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@xyflow/react";

export interface LayoutOptions {
    direction?: "LR" | "TB";
    nodeWidth?: number;
    nodeHeight?: number;
    rankSep?: number;
    nodeSep?: number;
}

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 80;

export function layoutGraph(
    nodes: Node[],
    edges: Edge[],
    {
        direction = "LR",
        nodeWidth = NODE_WIDTH,
        nodeHeight = NODE_HEIGHT,
        rankSep = 180,
        nodeSep = 100,
    }: LayoutOptions = {},
): { nodes: Node[]; edges: Edge[] } {
    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: direction, ranksep: rankSep, nodesep: nodeSep });

    for (const node of nodes) {
        g.setNode(node.id, {
            width: (node.width as number | undefined) ?? nodeWidth,
            height: (node.height as number | undefined) ?? nodeHeight,
        });
    }

    // Layout: skip back-edges (loops) so dagre stays a DAG.
    for (const edge of edges) {
        const skip = edge.data?.isLoop === true;
        if (skip) continue;
        g.setEdge(edge.source, edge.target);
    }

    dagre.layout(g);

    const positionedNodes: Node[] = nodes.map((node) => {
        const pos = g.node(node.id);
        if (!pos) return node;
        const width = (node.width as number | undefined) ?? nodeWidth;
        const height = (node.height as number | undefined) ?? nodeHeight;
        // Don't propagate width/height to the rendered node — CSS sizes it.
        // Layout uses width/height only for routing math.
        return {
            ...node,
            position: {
                x: pos.x - width / 2,
                y: pos.y - height / 2,
            },
        };
    });

    return { nodes: positionedNodes, edges };
}
