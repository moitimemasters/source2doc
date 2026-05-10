import {
    findEventDefAcrossPipelines,
    findPhaseDefAcrossPipelines,
    renderSummary,
    type EventKind,
} from "./schema";
import type { StreamEvent } from "@/lib/gateway/types";

export function getEventLabel(eventType: string): string {
    return findEventDefAcrossPipelines(eventType)?.label ?? eventType;
}

export function getEventIcon(eventType: string): string {
    return findEventDefAcrossPipelines(eventType)?.icon ?? "Circle";
}

export function getEventPhase(eventType: string): string {
    const def = findEventDefAcrossPipelines(eventType);
    return def?.phase ?? "other";
}

export function getEventKind(eventType: string): EventKind | "unknown" {
    return findEventDefAcrossPipelines(eventType)?.kind ?? "unknown";
}

export function isEventCollapsible(eventType: string): boolean {
    const def = findEventDefAcrossPipelines(eventType);
    if (!def) return true;
    if (def.collapsible === false) return false;
    return def.kind === "progress" || def.kind === "log";
}

export function getEventSummary(event: StreamEvent): string {
    const def = findEventDefAcrossPipelines(event.type);
    if (!def) return event.type;
    const rendered = renderSummary(def.summary_template, event.data ?? {});
    return rendered ?? def.label;
}

export function getPhaseLabel(phaseId: string): string {
    return findPhaseDefAcrossPipelines(phaseId)?.phase.label ?? phaseId;
}
