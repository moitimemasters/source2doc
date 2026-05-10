import { StreamEvent } from "@/lib/gateway/types";
import { findPhaseDefAcrossPipelines, knownPipelines } from "@/lib/pipelines/schema";
import { getEventPhase } from "./event-filters";

export interface EventGroup {
    phase: string;
    events: StreamEvent[];
    startTime?: Date;
    endTime?: Date;
    isExpanded?: boolean;
}

function pipelinePhaseOrder(): string[] {
    // Build the canonical phase ordering from whatever pipelines have been
    // registered via ``rememberPipeline``. Falls back to insertion order
    // from event grouping when no pipelines are loaded yet, so the UI keeps
    // working pre-schema-fetch.
    const order: string[] = [];
    const seen = new Set<string>();
    for (const pipeline of knownPipelines()) {
        for (const phase of pipeline.phases) {
            if (!seen.has(phase.id)) {
                seen.add(phase.id);
                order.push(phase.id);
            }
        }
    }
    return order;
}

export function groupEventsByPhase(events: StreamEvent[]): EventGroup[] {
    const groups = new Map<string, StreamEvent[]>();

    events.forEach((event) => {
        const phase = getEventPhase(event.type);
        if (!groups.has(phase)) {
            groups.set(phase, []);
        }
        groups.get(phase)!.push(event);
    });

    const ordered = pipelinePhaseOrder();
    const remainder: string[] = [];
    for (const phase of groups.keys()) {
        if (!ordered.includes(phase)) remainder.push(phase);
    }
    // "other" at the very end keeps the pre-existing UI affordance for
    // events emitted by a non-pipeline source.
    remainder.sort((a, b) => (a === "other" ? 1 : b === "other" ? -1 : a.localeCompare(b)));

    return [...ordered, ...remainder]
        .filter((phase) => groups.has(phase))
        .map((phase) => {
            const phaseEvents = groups.get(phase)!;
            return {
                phase,
                events: phaseEvents,
                startTime: undefined,
                endTime: undefined,
                isExpanded: false,
            };
        });
}

const FALLBACK_LABELS: Record<string, string> = {
    other: "Other Events",
};

const FALLBACK_ICONS: Record<string, string> = {
    other: "Circle",
};

export function getPhaseLabel(phase: string): string {
    const fromPipeline = findPhaseDefAcrossPipelines(phase);
    if (fromPipeline) return fromPipeline.phase.label;
    return FALLBACK_LABELS[phase] || phase;
}

export function getPhaseIcon(phase: string): string {
    const fromPipeline = findPhaseDefAcrossPipelines(phase);
    if (fromPipeline) return fromPipeline.phase.icon;
    return FALLBACK_ICONS[phase] || "Circle";
}

export function getPhaseStats(events: StreamEvent[]): {
    total: number;
    byPhase: Record<string, number>;
} {
    const byPhase: Record<string, number> = {};

    events.forEach((event) => {
        const phase = getEventPhase(event.type);
        byPhase[phase] = (byPhase[phase] || 0) + 1;
    });

    return {
        total: events.length,
        byPhase,
    };
}
