"use client";

import { useEffect, useMemo } from "react";
import { AlertTriangle, StopCircle } from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/lib/store/hooks";
import {
    connectToStream,
    disconnectFromStream,
} from "@/lib/store/streams-slice";
import { usePipelineGraph } from "@/lib/pipelines/usePipelineGraph";
import { StreamEvent } from "@/lib/gateway/types";
import { StreamHeader } from "./StreamHeader";
import { PipelineGraph } from "./graph/PipelineGraph";
import { EnhancedEventsContainer } from "./EnhancedEventsContainer";
import { ResumeFailedButton } from "./ResumeFailedButton";
import { RetryFailedButton } from "./RetryFailedButton";
import { StopGenerationButton } from "./StopGenerationButton";


/** Event types that may carry a structured ``reason`` field. Kept as a
 * Set so adding a new pipeline failure event is one-line. */
const FAILURE_EVENT_TYPES = new Set([
    "step.failed",
    "generation.failed",
    "codetour.failed",
    "codetour.followup_failed",
]);

interface LlmTimeoutBanner {
    model?: string;
    elapsedSeconds?: number;
    lastAttemptN?: number;
    errorMessage?: string;
}

/** Find the most recent failure event whose ``data.reason`` is
 * ``"llm_timeout"`` and return its display fields. Returns null if no
 * such event exists — the rest of the UI keeps its default behavior. */
function findLlmTimeout(events: StreamEvent[]): LlmTimeoutBanner | null {
    for (let i = events.length - 1; i >= 0; i--) {
        const ev = events[i];
        if (!FAILURE_EVENT_TYPES.has(ev.type)) continue;
        const data = (ev.data ?? {}) as Record<string, unknown>;
        if (data.reason !== "llm_timeout") continue;
        return {
            model: typeof data.model === "string" ? data.model : undefined,
            elapsedSeconds:
                typeof data.elapsed_s === "number" ? data.elapsed_s : undefined,
            lastAttemptN:
                typeof data.last_attempt_n === "number"
                    ? data.last_attempt_n
                    : undefined,
            errorMessage:
                typeof data.error_message === "string"
                    ? data.error_message
                    : undefined,
        };
    }
    return null;
}

interface StreamDetailContainerProps {
    streamId: string;
}

export function StreamDetailContainer({ streamId }: StreamDetailContainerProps) {
    const dispatch = useAppDispatch();
    const stream = useAppSelector((state) => state.streams.streams[streamId]);

    useEffect(() => {
        dispatch(connectToStream(streamId));

        return () => {
            dispatch(disconnectFromStream(streamId));
        };
    }, [dispatch, streamId]);

    const pipelineId = stream?.info.pipeline_id ?? null;
    const events = stream?.events ?? [];
    const { overallProgress } = usePipelineGraph(pipelineId, events);

    const llmTimeout = useMemo(() => findLlmTimeout(events), [events]);

    // The retry button is only useful for terminal failures. We trust the
    // derived status flipped by the slice; checking event types here would
    // duplicate that logic. For docgen streams the streamId equals the
    // generation_id — codetour streams use ``codetour:<gen_id>`` and aren't
    // retryable through this endpoint.
    const isFailed = stream?.info.status === "failed";
    const isStopped = stream?.info.status === "stopped";
    const isRunning =
        stream?.info.status === "running" || stream?.info.status === "pending";
    const isDocgenStream = !streamId.startsWith("codetour:");
    const showRetry = Boolean(isFailed && isDocgenStream);
    const showStoppedBanner = Boolean(isStopped && isDocgenStream);
    const showStop = Boolean(isRunning && isDocgenStream);
    const failureSummary = useMemo(() => {
        if (!isFailed) return null;
        for (let i = events.length - 1; i >= 0; i--) {
            const ev = events[i];
            if (
                ev.type === "task.failed" ||
                ev.type === "generation.failed" ||
                ev.type === "step.failed"
            ) {
                const data = (ev.data ?? {}) as Record<string, unknown>;
                const error = data.error;
                if (typeof error === "string" && error.length > 0) return error;
                const errorMessage = data.error_message;
                if (typeof errorMessage === "string" && errorMessage.length > 0) {
                    return errorMessage;
                }
                return ev.type;
            }
        }
        return null;
    }, [isFailed, events]);

    if (!stream) {
        return (
            <main className="min-h-screen bg-gradient-to-b from-background to-muted/20">
                <div className="container mx-auto px-4 py-16">
                    <div className="max-w-6xl mx-auto">
                        <div className="text-center">
                            <p className="text-muted-foreground">
                                Loading stream...
                            </p>
                        </div>
                    </div>
                </div>
            </main>
        );
    }

    return (
        <main className="min-h-screen bg-gradient-to-b from-background to-muted/20">
            <div className="container mx-auto px-4 py-16">
                <div className="max-w-6xl mx-auto">
                    <StreamHeader
                        streamId={streamId}
                        overallProgress={
                            stream.events.length > 0 ? overallProgress : null
                        }
                    />

                    {showStop && (
                        <div className="mb-4 flex justify-end">
                            <StopGenerationButton generationId={streamId} />
                        </div>
                    )}

                    {stream.error && (
                        <div className="mb-6 p-4 bg-destructive/10 border border-destructive rounded-lg text-destructive">
                            Error: {stream.error}
                        </div>
                    )}

                    {showStoppedBanner && (
                        <div
                            role="status"
                            data-testid="stopped-banner"
                            className="mb-6 p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700 rounded-lg text-amber-900 dark:text-amber-100 flex items-start gap-3"
                        >
                            <StopCircle className="h-5 w-5 flex-shrink-0 mt-0.5" />
                            <div className="flex-1 text-sm leading-relaxed">
                                <div className="font-semibold mb-1">
                                    Generation stopped
                                </div>
                                <div className="text-xs opacity-90 mb-3">
                                    Cancelled by user. Already-completed pages
                                    are preserved; pending events were
                                    skip+acked. Resume picks up from the last
                                    successful checkpoint.
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                    <ResumeFailedButton
                                        generationId={streamId}
                                    />
                                    <RetryFailedButton
                                        generationId={streamId}
                                    />
                                </div>
                            </div>
                        </div>
                    )}

                    {showRetry && (
                        <div
                            role="alert"
                            data-testid="retry-failed-banner"
                            className="mb-6 p-4 bg-destructive/10 border border-destructive rounded-lg text-destructive flex items-start gap-3"
                        >
                            <AlertTriangle className="h-5 w-5 flex-shrink-0 mt-0.5" />
                            <div className="flex-1 text-sm leading-relaxed">
                                <div className="font-semibold mb-1">
                                    Generation failed
                                </div>
                                {failureSummary && (
                                    <div className="text-xs opacity-90 mb-3 break-words">
                                        {failureSummary}
                                    </div>
                                )}
                                <div className="flex flex-wrap items-center gap-2">
                                    <ResumeFailedButton
                                        generationId={streamId}
                                    />
                                    <RetryFailedButton
                                        generationId={streamId}
                                    />
                                </div>
                            </div>
                        </div>
                    )}

                    {llmTimeout && (
                        <div
                            role="alert"
                            data-testid="llm-timeout-banner"
                            className="mb-6 p-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700 rounded-lg text-amber-900 dark:text-amber-100 flex items-start gap-3"
                        >
                            <AlertTriangle className="h-5 w-5 flex-shrink-0 mt-0.5" />
                            <div className="text-sm leading-relaxed">
                                <div className="font-semibold mb-1">
                                    LLM request timed out — try again or pick a
                                    smaller model
                                </div>
                                <div className="text-xs opacity-90">
                                    {llmTimeout.errorMessage ||
                                        `LLM call exhausted ${
                                            llmTimeout.lastAttemptN ?? "all"
                                        } retry attempts`}
                                    {llmTimeout.model && (
                                        <>
                                            {" — model "}
                                            <code className="font-mono">
                                                {llmTimeout.model}
                                            </code>
                                        </>
                                    )}
                                    {typeof llmTimeout.elapsedSeconds ===
                                        "number" && (
                                        <>
                                            {" ("}
                                            {llmTimeout.elapsedSeconds.toFixed(1)}
                                            {" s elapsed)"}
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {pipelineId && (
                        <div className="mb-8">
                            <h2 className="text-2xl font-bold mb-4">Pipeline</h2>
                            <PipelineGraph
                                pipelineId={pipelineId}
                                events={events}
                                height={640}
                            />
                        </div>
                    )}

                    <div>
                        <h2 className="text-2xl font-bold mb-6">Event Stream</h2>
                        <EnhancedEventsContainer events={stream.events} />
                    </div>
                </div>
            </div>
        </main>
    );
}
