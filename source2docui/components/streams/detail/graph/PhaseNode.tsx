"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
    AlertOctagon,
    AlertTriangle,
    CheckCheck,
    CheckCircle2,
    Circle,
    CircleStop,
    Database,
    Download,
    FolderPlus,
    GitBranch,
    Glasses,
    Layers,
    type LucideIcon,
    ListTree,
    Loader2,
    Map,
    Package,
    PenLine,
    RefreshCw,
    Scale,
    Workflow,
} from "lucide-react";
import type { PhaseRuntimeState } from "@/lib/pipelines/usePipelineGraph";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<string, LucideIcon> = {
    Download,
    Database,
    ListTree,
    Layers,
    PenLine,
    Workflow,
    CheckCheck,
    Glasses,
    Scale,
    Package,
    Map,
    RefreshCw,
    FolderPlus,
    GitBranch,
    Circle,
};

export function PhaseNode({ data }: NodeProps) {
    const state = data as unknown as PhaseRuntimeState;
    const Icon = ICON_MAP[state.phase.icon] ?? Circle;

    const statusClass = {
        idle: "border-border bg-card text-muted-foreground",
        active: "border-blue-500 bg-blue-50 dark:bg-blue-950/40 text-foreground shadow-md ring-2 ring-blue-500/40 animate-pulse",
        done: "border-green-500 bg-green-50 dark:bg-green-950/30 text-foreground",
        stopped:
            "border-amber-500 bg-amber-50 dark:bg-amber-950/30 text-foreground",
        error: "border-destructive bg-destructive/10 text-foreground",
    }[state.status];

    const StatusIndicator = {
        idle: <Circle className="h-4 w-4 text-muted-foreground" />,
        active: <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />,
        done: <CheckCircle2 className="h-4 w-4 text-green-500" />,
        stopped: <CircleStop className="h-4 w-4 text-amber-500" />,
        error: <AlertOctagon className="h-4 w-4 text-destructive" />,
    }[state.status];

    return (
        <div
            className={cn(
                "relative rounded-md border-2 px-3 py-2 transition-colors cursor-pointer flex flex-col gap-1.5",
                statusClass,
            )}
            style={{ minWidth: 220, maxWidth: 320 }}
        >
            {/* Error pin: shows past errors without recoloring the whole
                card. Status drives the main palette (active/done/etc),
                this little corner badge is the "X past errors" hint —
                hover to see the count. */}
            {state.errorEventCount > 0 && state.status !== "error" && (
                <div
                    className="absolute -top-2 -right-2 flex h-6 min-w-6 items-center justify-center gap-1 rounded-full border-2 border-background bg-destructive px-1.5 text-[11px] font-semibold text-destructive-foreground shadow-sm"
                    title={`${state.errorEventCount} past error${
                        state.errorEventCount === 1 ? "" : "s"
                    } (recovered or per-item)`}
                >
                    <AlertTriangle className="h-3 w-3" />
                    {state.errorEventCount}
                </div>
            )}
            <Handle
                id="left"
                type="target"
                position={Position.Left}
                className="!bg-muted-foreground"
            />
            <Handle
                id="top"
                type="target"
                position={Position.Top}
                className="!bg-muted-foreground"
            />
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <Icon className="h-5 w-5 flex-shrink-0" />
                    <div className="font-semibold text-base leading-tight">
                        {state.phase.label}
                    </div>
                </div>
                <div className="flex-shrink-0">{StatusIndicator}</div>
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>{state.eventCount} events</span>
            </div>
            <Handle
                id="right"
                type="source"
                position={Position.Right}
                className="!bg-muted-foreground"
            />
            <Handle
                id="bottom-source"
                type="source"
                position={Position.Bottom}
                style={{ left: "30%" }}
                className="!bg-muted-foreground"
            />
            <Handle
                id="bottom-target"
                type="target"
                position={Position.Bottom}
                style={{ left: "70%" }}
                className="!bg-muted-foreground"
            />
        </div>
    );
}
