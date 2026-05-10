import { StreamEvent } from "@/lib/gateway/types";
import { findEventDefAcrossPipelines } from "@/lib/pipelines/schema";

export interface CollapsedEvent {
    type: string;
    count: number;
    startIndex: number;
    endIndex: number;
    events: StreamEvent[];
    data?: Record<string, unknown>;
}

export function collapseConsecutiveEvents(
    events: StreamEvent[],
): CollapsedEvent[] {
    if (events.length === 0) return [];

    const collapsed: CollapsedEvent[] = [];
    let currentGroup: StreamEvent[] = [events[0]];
    let startIndex = 0;

    for (let i = 1; i < events.length; i++) {
        const current = events[i];
        const previous = events[i - 1];

        // Group if same type and similar data structure
        if (shouldGroupEvents(current, previous)) {
            currentGroup.push(current);
        } else {
            // Finalize current group
            collapsed.push(createCollapsedEvent(currentGroup, startIndex));
            currentGroup = [current];
            startIndex = i;
        }
    }

    // Add last group
    collapsed.push(createCollapsedEvent(currentGroup, startIndex));

    return collapsed;
}

function shouldGroupEvents(event1: StreamEvent, event2: StreamEvent): boolean {
    // Same type is required
    if (event1.type !== event2.type) return false;

    // Honor registry: only progress/log events collapse; everything else stays distinct.
    const def = findEventDefAcrossPipelines(event1.type);
    if (def) {
        if (def.collapsible === false) return false;
        if (def.kind !== "progress" && def.kind !== "log") return false;
    }

    // Group events with similar data structure
    const keys1 = Object.keys(event1.data || {}).sort();
    const keys2 = Object.keys(event2.data || {}).sort();

    return JSON.stringify(keys1) === JSON.stringify(keys2);
}

function createCollapsedEvent(
    events: StreamEvent[],
    startIndex: number,
): CollapsedEvent {
    const count = events.length;
    const endIndex = startIndex + count - 1;

    // For grouped events, use aggregated data if applicable
    let data: Record<string, unknown> | undefined;

    if (count > 1) {
        // Try to aggregate numeric values
        data = aggregateEventData(events);
    } else {
        data = events[0].data;
    }

    return {
        type: events[0].type,
        count,
        startIndex,
        endIndex,
        events,
        data,
    };
}

function aggregateEventData(
    events: StreamEvent[],
): Record<string, unknown> | undefined {
    if (events.length === 0) return undefined;

    const firstData = events[0].data;
    if (!firstData) return undefined;

    const aggregated: Record<string, unknown> = {};

    // For each key in the first event
    for (const key of Object.keys(firstData)) {
        const values = events
            .map((e) => e.data?.[key])
            .filter((v) => v !== undefined);

        if (values.length === 0) continue;

        // If all values are numbers, sum them
        if (values.every((v) => typeof v === "number")) {
            aggregated[key] = values.reduce(
                (sum, v) => sum + (v as number),
                0,
            );
        }
        // If all values are the same, use that value
        else if (values.every((v) => v === values[0])) {
            aggregated[key] = values[0];
        }
        // Otherwise, show range or list
        else {
            aggregated[key] = `${values[0]}...${values[values.length - 1]}`;
        }
    }

    return Object.keys(aggregated).length > 0 ? aggregated : undefined;
}
