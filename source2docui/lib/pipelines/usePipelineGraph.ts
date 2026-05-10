"use client";

import { useEffect, useMemo, useState } from "react";
import {
    Pipeline,
    PipelineSchema,
    EventDef,
    PhaseDef,
    getEventDef,
    rememberPipeline,
    filterPhasesForMode,
} from "./schema";
import type { StreamEvent } from "@/lib/gateway/types";

export type PhaseStatus = "idle" | "active" | "done" | "stopped" | "error";

export interface PhaseRuntimeState {
    phase: PhaseDef;
    status: PhaseStatus;
    eventCount: number;
    transitionEventCount: number;
    progressEventCount: number;
    errorEventCount: number;
    lastEvent?: StreamEvent;
    firstEventAt?: string;
    lastEventAt?: string;
}

export interface PipelineGraphState {
    pipeline: Pipeline | null;
    loading: boolean;
    error: string | null;
    phases: PhaseRuntimeState[];
    activePhase: string | null;
    overallProgress: number;
    eventsByPhase: Record<string, StreamEvent[]>;
}

const cache = new Map<string, Promise<Pipeline>>();

async function fetchSchema(pipelineId: string): Promise<Pipeline> {
    if (!cache.has(pipelineId)) {
        const promise = fetch(
            `/api/gateway/pipelines/${encodeURIComponent(pipelineId)}/schema`,
            { headers: { "Content-Type": "application/json" } },
        ).then(async (response) => {
            if (!response.ok) {
                throw new Error(
                    `Failed to fetch pipeline schema for ${pipelineId} (${response.status})`,
                );
            }
            const json = await response.json();
            return PipelineSchema.parse(json);
        });
        cache.set(pipelineId, promise);
    }
    return cache.get(pipelineId)!;
}

export function usePipelineSchema(pipelineId: string | null | undefined): {
    pipeline: Pipeline | null;
    loading: boolean;
    error: string | null;
} {
    const [pipeline, setPipeline] = useState<Pipeline | null>(null);
    const [loading, setLoading] = useState<boolean>(Boolean(pipelineId));
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        if (!pipelineId) {
            setPipeline(null);
            setLoading(false);
            return;
        }
        setLoading(true);
        setError(null);
        fetchSchema(pipelineId)
            .then((schema) => {
                rememberPipeline(schema);
                if (!cancelled) setPipeline(schema);
            })
            .catch((err: Error) => {
                if (!cancelled) setError(err.message);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [pipelineId]);

    return { pipeline, loading, error };
}

export function computeGraphState(
    pipeline: Pipeline | null,
    events: StreamEvent[],
): Pick<PipelineGraphState, "phases" | "activePhase" | "overallProgress" | "eventsByPhase"> {
    if (!pipeline) {
        return {
            phases: [],
            activePhase: null,
            overallProgress: 0,
            eventsByPhase: {},
        };
    }

    // Derive the run's effective mode from the events seen so far. This
    // lets us hide branches that the run will never enter — e.g. the
    // ``iterative`` phase on a full-mode run, or ``plan``/``subplan`` on
    // an incremental run. Mode resolution is best-effort: we fall back
    // to ``"full"`` (the default the gateway stamps on bundles) if no
    // disambiguating event has fired yet.
    let mode: string = "full";
    for (const event of events) {
        if (event.type === "iterative.index_completed") {
            mode = "incremental";
            break;
        }
    }
    const visiblePhases = filterPhasesForMode(pipeline, mode);
    const visiblePhaseIds = new Set(visiblePhases.map((p) => p.id));

    const eventsByPhase: Record<string, StreamEvent[]> = {};
    for (const phase of visiblePhases) eventsByPhase[phase.id] = [];

    const phaseStatus: Record<string, PhaseStatus> = {};
    for (const phase of visiblePhases) phaseStatus[phase.id] = "idle";

    let activePhase: string | null = null;
    let terminal = false;
    let terminalFailed = false;
    // ``task.stopped`` is a terminal event but it's neither success nor
    // failure — the user halted the run mid-flight. Tracking it separately
    // keeps the post-walk passes from painting every non-error phase green
    // (the terminal-success branch) or red (the terminal-failure branch).
    // Phases that were ``active`` at the moment of stop become ``stopped``;
    // ``idle`` / ``done`` / ``error`` carry over unchanged.
    let terminalStopped = false;

    // Phases participating in a cycle (self-loop or via revision/retry edges)
    // process work per-item in parallel. We can't decide their done-ness from
    // a single transition out, so the auto-done branch is skipped for them.
    // A second pass below derives the real status from per-page progression.
    // Per-page-flow phases: pages stream through them, so we drive their
    // status from the page-tracker (pendingByPhase) below instead of the
    // last-event-wins logic in the main pass. Hardcoded because the
    // automatic cycle-detection used to fold in one-shot phases with
    // self-emit edges (subplan fan-out, normalize self-loop) — which
    // then froze them at "active" forever even after all pages had
    // moved on.
    const PER_PAGE_FLOW_PHASES = new Set([
        "write",
        "diagram",
        "review",
        "evaluate",
        "normalize",
    ]);
    // Page-flow ordering used to decide when an upstream phase has
    // truly drained — if a strictly-later phase still has pages in
    // flight, the earlier phase is done even though pendingByPhase[X]
    // == 0 (a single page can be at-most-one phase at any moment). The
    // last entry ``finalize`` is included so "page is in finalize"
    // counts as draining everything before it.
    const PAGE_FLOW_ORDER = [
        "write",
        "diagram",
        "review",
        "evaluate",
        "normalize",
        "finalize",
    ];
    const phasesWithLoops = new Set<string>(
        [...PER_PAGE_FLOW_PHASES].filter((p) => visiblePhaseIds.has(p)),
    );

    // Map of page_id -> current phase, updated as page-level transitions
    // fire. Used after the main event walk to flip per-page phases between
    // "active" (some pages still in-flight) and "done" (all pages moved to
    // a strictly-later phase). Stage events with a ``page_id`` field are
    // the only ones that participate; section / diagram fan-out events are
    // ignored to keep the model strictly per-page.
    const pageCurrentPhase = new Map<string, string>();
    const pageEventToTargetPhase: Record<string, string> = {
        "page.write_requested": "write",
        "page.written": "diagram",
        "page.diagrams_completed": "review",
        "page.reviewed": "evaluate",
        "page.revision_requested": "write",
        "page.completed": "normalize",
        "page.normalized": "finalize",
    };
    // Terminal events for a single page — once seen, that page no longer
    // counts as "in-flight" for any phase.
    const pageDoneEvents = new Set(["doc.page.created", "doc.page.failed", "page.failed"]);

    const counters: Record<string, {
        all: number;
        transition: number;
        progress: number;
        error: number;
        first?: StreamEvent;
        last?: StreamEvent;
    }> = {};
    for (const phase of visiblePhases) {
        counters[phase.id] = { all: 0, transition: 0, progress: 0, error: 0 };
    }

    // Noisy progress events that fire thousands of times per generation
    // (chunk.created ~20k, file.ingested ~3k for fastapi). They never drive
    // a transition, so for them we just bump the per-phase counter and skip
    // the rest of the work — no Set lookup, no eventsByPhase push, no
    // transitions filter. Saves ~95% of the graph-state work on long runs.
    const NOISY = new Set(["chunk.created", "file.ingested", "embeddings.batch"]);

    const seen = new Set<string>();
    for (const event of events) {
        if (NOISY.has(event.type)) {
            const def = getEventDef(pipeline, event.type);
            if (def) {
                const c = counters[def.phase];
                if (c) {
                    c.all += 1;
                    c.progress += 1;
                }
            }
            continue;
        }
        if (seen.has(event.id)) continue;
        seen.add(event.id);
        const def: EventDef | undefined = getEventDef(pipeline, event.type);
        if (!def) continue;

        const phaseId = def.phase;
        eventsByPhase[phaseId]?.push(event);
        const c = counters[phaseId];
        if (c) {
            c.all += 1;
            if (def.kind === "transition") c.transition += 1;
            if (def.kind === "progress") c.progress += 1;
            if (def.kind === "error") c.error += 1;
            if (!c.first) c.first = event;
            c.last = event;
        }

        // Per-page failures (one page out of many) shouldn't redden the
        // whole phase — they're recorded in the error counter for the
        // node tooltip but the phase status flows normally so the rest
        // of the pages can complete it. Task-level errors below DO mark
        // the phase red.
        const PER_PAGE_ERROR_TYPES = new Set([
            "page.failed",
            "doc.page.failed",
        ]);

        if (event.type === "task.resumed") {
            // Resume invalidates prior task-level error AND stop markers.
            // Work is moving forward again, so any phase that was painted
            // red (``task.failed`` / ``step.failed`` / ``ingest.failed`` /
            // ``handler.error``) or amber (``task.stopped``) gets demoted
            // back to "active". All three pipeline-level terminal flags
            // are cleared so the post-walk passes treat the run as live —
            // critically, ``terminalStopped`` must clear too, otherwise a
            // later ``generation.completed`` would skip the
            // success-fill-all-phases branch and the "active → stopped"
            // pass would still fire, leaving the entire graph amber.
            for (const pid of Object.keys(phaseStatus)) {
                if (phaseStatus[pid] === "error" || phaseStatus[pid] === "stopped") {
                    phaseStatus[pid] = "active";
                }
            }
            terminal = false;
            terminalFailed = false;
            terminalStopped = false;
        } else if (def.kind === "error") {
            if (!PER_PAGE_ERROR_TYPES.has(event.type)) {
                phaseStatus[phaseId] = "error";
            }
        } else if (def.kind === "terminal") {
            terminal = true;
            if (event.type === "task.stopped") {
                // Don't paint any phase yet — the post-walk pass below
                // converts ``active`` → ``stopped`` and leaves idle/done
                // phases untouched.
                terminalStopped = true;
            } else if (def.type.endsWith(".failed")) {
                phaseStatus[phaseId] = "error";
                terminalFailed = true;
            } else {
                phaseStatus[phaseId] = "done";
            }
        } else if (def.kind === "transition") {
            // Mark the phase the transition exits as active by default;
            // transitions out of a phase mean it's working on something.
            if (phaseStatus[phaseId] !== "error") {
                phaseStatus[phaseId] = "active";
            }
            // If the transition has a non-loop target phase, the source phase becomes done.
            const transitions = pipeline.transitions.filter(
                (t) => t.trigger_event === event.type && !t.is_loop && !t.is_failure,
            );
            for (const t of transitions) {
                if (
                    t.source !== "_entry_" &&
                    visiblePhaseIds.has(t.source) &&
                    phaseStatus[t.source] !== "error" &&
                    !phasesWithLoops.has(t.source)
                ) {
                    phaseStatus[t.source] = "done";
                }
                if (
                    t.target !== "_terminal_ok_" &&
                    t.target !== "_terminal_fail_" &&
                    phaseStatus[t.target] !== "error" &&
                    phaseStatus[t.target] !== "done"
                ) {
                    phaseStatus[t.target] = "active";
                    activePhase = t.target;
                }
            }
        }

        // Per-page progression — flips an individual page's "current phase"
        // as it walks through the pipeline. Used below to decide whether a
        // looped phase still has any in-flight pages.
        //
        // ``page.write_requested`` is special: the worker emits it with the
        // page_id nested inside ``page_spec.page_id`` (and no top-level
        // ``page_id``), so we have to look in both places. Without the
        // ``page_spec`` fallback the write phase never accumulates in-flight
        // pages, the second pass below treats it as idle, and the "Writing
        // Pages" node never lights up blue.
        const data = (event as unknown as { data?: Record<string, unknown> }).data;
        let pageId: string | null = null;
        if (data && typeof data === "object") {
            if (typeof data.page_id === "string") {
                pageId = data.page_id;
            } else if (
                data.page_spec &&
                typeof data.page_spec === "object" &&
                "page_id" in (data.page_spec as Record<string, unknown>)
            ) {
                const spec = data.page_spec as Record<string, unknown>;
                if (typeof spec.page_id === "string") pageId = spec.page_id;
            }
        }
        if (pageId) {
            if (pageDoneEvents.has(event.type)) {
                pageCurrentPhase.delete(pageId);
            } else if (event.type in pageEventToTargetPhase) {
                pageCurrentPhase.set(pageId, pageEventToTargetPhase[event.type]);
            }
        }
    }

    // Second pass: flip phases-in-cycle based on whether any page is
    // currently inside them. Phase done iff every page that ever entered
    // it has moved on.
    {
        const pendingByPhase: Record<string, number> = {};
        for (const phase of visiblePhases) pendingByPhase[phase.id] = 0;
        for (const phaseId of pageCurrentPhase.values()) {
            if (pendingByPhase[phaseId] !== undefined) {
                pendingByPhase[phaseId] += 1;
            }
        }
        // Find the EARLIEST (leftmost in PAGE_FLOW_ORDER) per-page phase
        // that currently holds any page. A page can only be at-most-one
        // phase at a time, so the earliest live page tells us how far
        // upstream work still extends — every phase strictly before
        // ``minActiveIdx`` has pages still queued upstream and will
        // eventually receive more work, while every phase strictly
        // before-or-equal to ``minActiveIdx`` is genuinely active.
        // Phases strictly AFTER ``minActiveIdx`` whose own pending is
        // 0 have drained everything they will ever see (no upstream
        // page can skip phases) — mark them done.
        let minActiveIdx = Infinity;
        for (const currentPhaseId of pageCurrentPhase.values()) {
            const idx = PAGE_FLOW_ORDER.indexOf(currentPhaseId);
            if (idx >= 0 && idx < minActiveIdx) {
                minActiveIdx = idx;
            }
        }
        for (const phaseId of phasesWithLoops) {
            if (phaseStatus[phaseId] === "error") continue;
            const hadEvents = (counters[phaseId]?.all ?? 0) > 0;
            if (!hadEvents) continue;

            const pending = pendingByPhase[phaseId] ?? 0;
            if (pending > 0) {
                phaseStatus[phaseId] = "active";
                continue;
            }

            // pending == 0. Three sub-cases:
            //   (a) every live page has already moved past this phase
            //       (minActiveIdx > myIdx) → truly drained → done.
            //   (b) some page is still at or before this phase, so
            //       upstream is still feeding work → active.
            //   (c) no live pages anywhere AND generation terminated
            //       cleanly → done.
            const myIdx = PAGE_FLOW_ORDER.indexOf(phaseId);
            const everyLivePagePastUs =
                myIdx >= 0 && minActiveIdx !== Infinity && minActiveIdx > myIdx;
            if (everyLivePagePastUs) {
                phaseStatus[phaseId] = "done";
            } else if (terminal && !terminalFailed && !terminalStopped) {
                phaseStatus[phaseId] = "done";
            } else {
                // Includes the stopped case — phases that were genuinely
                // mid-work stay "active" through this pass and get
                // promoted to "stopped" below. Idle phases (no events at
                // all) were already short-circuited by ``hadEvents``.
                phaseStatus[phaseId] = "active";
            }
        }
    }

    // If pipeline is terminal-success, all non-error phases become done.
    // Skip on user-initiated stop — the run didn't complete, and painting
    // every untouched phase green is misleading.
    if (terminal && !terminalFailed && !terminalStopped) {
        for (const phase of visiblePhases) {
            if (phaseStatus[phase.id] !== "error") {
                phaseStatus[phase.id] = "done";
            }
        }
        activePhase = null;
    }

    // If pipeline failed, every phase that's still active becomes error.
    if (terminal && terminalFailed) {
        for (const phase of visiblePhases) {
            if (phaseStatus[phase.id] === "active") {
                phaseStatus[phase.id] = "error";
            }
        }
        activePhase = null;
    }

    // If pipeline was user-stopped, ``active`` phases (work in progress at
    // the moment of stop) become ``stopped`` (amber). ``idle`` phases that
    // never received any work stay grey, ``done`` phases that genuinely
    // completed before the stop stay green, and ``error`` markers carry
    // over. This matches the user's mental model: "what was running got
    // paused, what was already finished is finished, what hadn't started
    // hasn't started".
    if (terminal && terminalStopped) {
        for (const phase of visiblePhases) {
            if (phaseStatus[phase.id] === "active") {
                phaseStatus[phase.id] = "stopped";
            }
        }
        activePhase = null;
    }

    // Overall progress: weighted sum of done phases. Active and stopped
    // phases count half — stopped represents "was working when halted",
    // so it freezes at the same partial-credit level as active.
    let totalWeight = 0;
    let achieved = 0;
    for (const phase of visiblePhases) {
        const w = phase.weight || 1;
        totalWeight += w;
        const status = phaseStatus[phase.id];
        if (status === "done") achieved += w;
        else if (status === "active" || status === "stopped") achieved += w * 0.5;
    }
    const overallProgress = totalWeight > 0 ? Math.round((achieved / totalWeight) * 100) : 0;

    const phases: PhaseRuntimeState[] = visiblePhases.map((phase) => {
        const c = counters[phase.id];
        return {
            phase,
            status: phaseStatus[phase.id],
            eventCount: c.all,
            transitionEventCount: c.transition,
            progressEventCount: c.progress,
            errorEventCount: c.error,
            lastEvent: c.last,
            firstEventAt: c.first?.id,
            lastEventAt: c.last?.id,
        };
    });

    return { phases, activePhase, overallProgress, eventsByPhase };
}

export function usePipelineGraph(
    pipelineId: string | null | undefined,
    events: StreamEvent[],
): PipelineGraphState {
    const { pipeline, loading, error } = usePipelineSchema(pipelineId);

    const computed = useMemo(
        () => computeGraphState(pipeline, events),
        [pipeline, events],
    );

    return { pipeline, loading, error, ...computed };
}
