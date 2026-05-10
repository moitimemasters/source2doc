"use client";

import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "@/components/ui/sheet";
import {
    AlertCircle,
    AlertOctagon,
    Activity,
    CheckCircle2,
    Circle,
} from "lucide-react";
import type { PhaseRuntimeState } from "@/lib/pipelines/usePipelineGraph";
import { renderSummary, type Pipeline, getEventDef } from "@/lib/pipelines/schema";
import type { StreamEvent } from "@/lib/gateway/types";
import { cn } from "@/lib/utils";

interface PhaseDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    phaseState: PhaseRuntimeState | null;
    pipeline: Pipeline | null;
    events: StreamEvent[];
}

const KIND_COLOR: Record<string, string> = {
    transition: "text-blue-600 dark:text-blue-400",
    progress: "text-muted-foreground",
    log: "text-muted-foreground",
    error: "text-destructive",
    terminal: "text-green-600 dark:text-green-400",
};

const KIND_ICON: Record<string, typeof Activity> = {
    transition: Activity,
    progress: Circle,
    log: Circle,
    error: AlertOctagon,
    terminal: CheckCircle2,
};

export function PhaseDrawer({
    open,
    onOpenChange,
    phaseState,
    pipeline,
    events,
}: PhaseDrawerProps) {
    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="w-full sm:max-w-xl overflow-y-auto">
                <SheetHeader>
                    <SheetTitle>{phaseState?.phase.label ?? "Phase"}</SheetTitle>
                    {phaseState?.phase.description && (
                        <SheetDescription>{phaseState.phase.description}</SheetDescription>
                    )}
                </SheetHeader>
                {phaseState && (
                    <div className="px-4 pb-6 space-y-4">
                        <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
                            <span>Status: <span className="text-foreground font-medium capitalize">{phaseState.status}</span></span>
                            <span>{phaseState.eventCount} events</span>
                            {phaseState.errorEventCount > 0 && (
                                <span className="text-destructive">
                                    {phaseState.errorEventCount} errors
                                </span>
                            )}
                        </div>

                        {events.length === 0 ? (
                            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                                <AlertCircle className="mx-auto mb-2 h-5 w-5" />
                                No events recorded for this phase yet.
                            </div>
                        ) : (
                            <ul className="space-y-2">
                                {events.map((event) => {
                                    const def = pipeline
                                        ? getEventDef(pipeline, event.type)
                                        : undefined;
                                    const KindIcon = def ? KIND_ICON[def.kind] : Activity;
                                    const summary = renderSummary(
                                        def?.summary_template,
                                        event.data ?? {},
                                    );
                                    return (
                                        <li
                                            key={event.id}
                                            className="rounded-md border border-border p-3 text-sm"
                                        >
                                            <div className="flex items-start gap-2">
                                                <KindIcon
                                                    className={cn(
                                                        "h-4 w-4 mt-0.5 flex-shrink-0",
                                                        def ? KIND_COLOR[def.kind] : "",
                                                    )}
                                                />
                                                <div className="min-w-0 flex-1">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <span className="font-medium">
                                                            {def?.label ?? event.type}
                                                        </span>
                                                        <span className="text-[11px] text-muted-foreground font-mono">
                                                            {event.id.split("-")[0]}
                                                        </span>
                                                    </div>
                                                    {summary && (
                                                        <div className="text-muted-foreground text-xs mt-0.5">
                                                            {summary}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}
