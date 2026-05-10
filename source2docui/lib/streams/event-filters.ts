import { StreamEvent } from "@/lib/gateway/types";
import { findEventDefAcrossPipelines } from "@/lib/pipelines/schema";

export interface EventFilterState {
    search: string;
    phase: string;
    eventType: string;
}

export const DEFAULT_FILTERS: EventFilterState = {
    search: "",
    phase: "all",
    eventType: "all",
};

const HEARTBEAT_TYPES = new Set(["ping", "pong", "heartbeat"]);

// High-frequency progress events. A single fastapi gen emits ~3000 of
// chunk.created and ~500 of file.ingested. Rendering them all flattens
// the browser. Counts still surface via EventStats / phase totals.
const NOISY_EVENT_TYPES = new Set([
    "chunk.created",
    "file.ingested",
    "embeddings.batch",
]);

export function isHeartbeatEvent(event: StreamEvent): boolean {
    return HEARTBEAT_TYPES.has(event.type);
}

export function isNoisyEvent(event: StreamEvent): boolean {
    return NOISY_EVENT_TYPES.has(event.type);
}

export function dropHeartbeats(events: StreamEvent[]): StreamEvent[] {
    return events.filter((e) => !isHeartbeatEvent(e) && !isNoisyEvent(e));
}

export function getEventPhase(eventType: string): string {
    return findEventDefAcrossPipelines(eventType)?.phase ?? "other";
}

export function filterEvents(
    events: StreamEvent[],
    filters: EventFilterState,
): StreamEvent[] {
    return events.filter((event) => {
        // Search filter
        if (filters.search) {
            const searchLower = filters.search.toLowerCase();
            const matchesType = event.type.toLowerCase().includes(searchLower);
            const matchesData = event.data
                ? JSON.stringify(event.data).toLowerCase().includes(searchLower)
                : false;
            if (!matchesType && !matchesData) {
                return false;
            }
        }

        // Phase filter
        if (filters.phase !== "all") {
            const eventPhase = getEventPhase(event.type);
            if (eventPhase !== filters.phase) {
                return false;
            }
        }

        // Event type filter
        if (filters.eventType !== "all" && event.type !== filters.eventType) {
            return false;
        }

        return true;
    });
}

export function getAvailablePhases(events: StreamEvent[]): string[] {
    const phases = new Set<string>();
    events.forEach((event) => {
        phases.add(getEventPhase(event.type));
    });
    return Array.from(phases).sort();
}

export function getAvailableEventTypes(events: StreamEvent[]): string[] {
    const types = new Set<string>();
    events.forEach((event) => {
        types.add(event.type);
    });
    return Array.from(types).sort();
}
