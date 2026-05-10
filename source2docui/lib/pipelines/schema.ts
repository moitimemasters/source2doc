import { z } from "zod";

export const ENTRY_NODE = "_entry_";
export const TERMINAL_OK_NODE = "_terminal_ok_";
export const TERMINAL_FAIL_NODE = "_terminal_fail_";

export const EventKindSchema = z.enum([
    "transition",
    "progress",
    "log",
    "error",
    "terminal",
]);

export const EventDefSchema = z.object({
    type: z.string(),
    kind: EventKindSchema,
    phase: z.string(),
    label: z.string(),
    icon: z.string().default("Activity"),
    summary_template: z.string().nullable().optional(),
    color: z.string().nullable().optional(),
    collapsible: z.boolean().default(true),
});

export const PhaseDefSchema = z.object({
    id: z.string(),
    label: z.string(),
    icon: z.string().default("Circle"),
    weight: z.number().default(1.0),
    description: z.string().nullable().optional(),
    // Optional list of pipeline branches that include this phase. Empty
    // == "applies to every mode" (the default for full-mode-only pipelines
    // that haven't opted in). Consumed by ``filterPhasesForMode`` to hide
    // permanently-idle branch nodes from the graph (e.g. ``iterative``
    // for full-mode runs, ``plan``/``subplan`` for incremental runs).
    applies_to_modes: z.array(z.string()).default([]),
});

export const TransitionDefSchema = z.object({
    source: z.string(),
    target: z.string(),
    trigger_event: z.string(),
    is_loop: z.boolean().default(false),
    is_failure: z.boolean().default(false),
});

export const PipelineSchema = z.object({
    id: z.string(),
    label: z.string(),
    entry_event: z.string(),
    terminal_events: z.array(z.string()).default([]),
    phases: z.array(PhaseDefSchema),
    events: z.array(EventDefSchema),
    transitions: z.array(TransitionDefSchema),
});

export type EventKind = z.infer<typeof EventKindSchema>;
export type EventDef = z.infer<typeof EventDefSchema>;
export type PhaseDef = z.infer<typeof PhaseDefSchema>;
export type TransitionDef = z.infer<typeof TransitionDefSchema>;
export type Pipeline = z.infer<typeof PipelineSchema>;

export function getEventDef(pipeline: Pipeline, eventType: string): EventDef | undefined {
    return pipeline.events.find((e) => e.type === eventType);
}

const loadedPipelines = new Map<string, Pipeline>();

export function rememberPipeline(pipeline: Pipeline): void {
    loadedPipelines.set(pipeline.id, pipeline);
}

export function findEventDefAcrossPipelines(eventType: string): EventDef | undefined {
    for (const pipeline of loadedPipelines.values()) {
        const def = getEventDef(pipeline, eventType);
        if (def) return def;
    }
    return undefined;
}

export function findPhaseDefAcrossPipelines(
    phaseId: string,
): { pipeline: Pipeline; phase: PhaseDef } | undefined {
    for (const pipeline of loadedPipelines.values()) {
        const phase = getPhaseDef(pipeline, phaseId);
        if (phase) return { pipeline, phase };
    }
    return undefined;
}

export function knownPipelines(): Pipeline[] {
    return Array.from(loadedPipelines.values());
}

export function getPhaseDef(pipeline: Pipeline, phaseId: string): PhaseDef | undefined {
    return pipeline.phases.find((p) => p.id === phaseId);
}

/** Return the phases that should be rendered for a given run mode.
 *
 * Phases with an empty ``applies_to_modes`` are always shown (default
 * for backwards compat). Phases with a non-empty list are shown only
 * when ``mode`` is one of the listed values. ``mode === null`` is the
 * "show everything" fallback for pages that don't yet know what kind
 * of run they're observing (e.g. before any event has been received).
 */
export function filterPhasesForMode(
    pipeline: Pipeline,
    mode: string | null,
): PhaseDef[] {
    if (mode === null) return pipeline.phases;
    return pipeline.phases.filter(
        (phase) =>
            phase.applies_to_modes.length === 0 ||
            phase.applies_to_modes.includes(mode),
    );
}

export function phaseForEvent(pipeline: Pipeline, eventType: string): string | undefined {
    return getEventDef(pipeline, eventType)?.phase;
}

export function transitionsForEvent(
    pipeline: Pipeline,
    eventType: string,
): TransitionDef[] {
    return pipeline.transitions.filter((t) => t.trigger_event === eventType);
}

const SUMMARY_VAR_RE = /\{\{\s*([\w.]+)\s*\}\}/g;

function readPath(obj: unknown, path: string): unknown {
    const parts = path.split(".");
    let cur: unknown = obj;
    for (const part of parts) {
        if (cur && typeof cur === "object" && part in (cur as Record<string, unknown>)) {
            cur = (cur as Record<string, unknown>)[part];
        } else {
            return undefined;
        }
    }
    return cur;
}

export function renderSummary(
    template: string | null | undefined,
    data: Record<string, unknown>,
): string | null {
    if (!template) return null;
    let hadMissing = false;
    const rendered = template.replace(SUMMARY_VAR_RE, (_, key) => {
        const value = readPath(data, key);
        if (value === undefined || value === null || value === "") {
            hadMissing = true;
            return "";
        }
        return String(value);
    });
    if (hadMissing && rendered.trim() === "") return null;
    return rendered.trim() || null;
}
