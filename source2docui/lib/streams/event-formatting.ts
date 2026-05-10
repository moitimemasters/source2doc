import { StreamEvent } from "@/lib/gateway/types";
import {
    findEventDefAcrossPipelines,
    renderSummary,
} from "@/lib/pipelines/schema";

export interface FormattedEventData {
    key: string;
    value: string;
    type: "string" | "number" | "boolean" | "object";
}

export function formatEventData(
    data: Record<string, unknown>,
): FormattedEventData[] {
    return Object.entries(data).map(([key, value]) => {
        let formattedValue: string;
        let type: FormattedEventData["type"];

        if (typeof value === "string") {
            formattedValue = value;
            type = "string";
        } else if (typeof value === "number") {
            formattedValue = value.toLocaleString();
            type = "number";
        } else if (typeof value === "boolean") {
            formattedValue = value ? "Yes" : "No";
            type = "boolean";
        } else if (value === null || value === undefined) {
            formattedValue = "—";
            type = "string";
        } else {
            formattedValue = JSON.stringify(value, null, 2);
            type = "object";
        }

        return {
            key: formatKey(key),
            value: formattedValue,
            type,
        };
    });
}

function formatKey(key: string): string {
    return key
        .split("_")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
}

export function getEventSummary(event: StreamEvent): string {
    const def = findEventDefAcrossPipelines(event.type);
    if (!def) return event.type;
    const rendered = renderSummary(def.summary_template, event.data ?? {});
    return rendered ?? def.label;
}

export function shouldShowDataInline(event: StreamEvent): boolean {
    const def = findEventDefAcrossPipelines(event.type);
    return def?.kind === "progress";
}

export function getEventColor(eventType: string): string {
    const def = findEventDefAcrossPipelines(eventType);
    switch (def?.kind) {
        case "terminal":
            return "text-green-600 dark:text-green-400";
        case "transition":
            return "text-blue-600 dark:text-blue-400";
        case "progress":
            return "text-yellow-600 dark:text-yellow-400";
        case "error":
            return "text-red-600 dark:text-red-400";
        default:
            return "text-muted-foreground";
    }
}
