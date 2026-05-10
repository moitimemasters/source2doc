"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
    AlertCircle,
    Ban,
    CheckCircle2,
    Loader2,
    XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { codetourAPI } from "@/lib/codetour-api";
import {
    SseStatusIndicator,
    type SseStatus,
} from "@/components/sse-status-indicator";

type TerminalStatus = "completed" | "failed" | "cancelled";
type LiveStatus = "pending" | "running" | TerminalStatus;

const SSE_STALE_TIMEOUT_MS = 15_000;

interface StepPreview {
    index: number;
    title: string;
    file: string;
    line: number;
}

interface RejectedStep {
    reason: string;
    title?: string;
    file?: string;
}

interface Props {
    tourId: string;
    initialStatus: LiveStatus;
    initialQuery?: string;
    maxSteps?: number;
}

export function TourLiveView({
    tourId,
    initialStatus,
    initialQuery,
    maxSteps,
}: Props) {
    const router = useRouter();
    const [status, setStatus] = useState<LiveStatus>(initialStatus);
    const [steps, setSteps] = useState<StepPreview[]>([]);
    const [rejected, setRejected] = useState<RejectedStep[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [isCancelling, setIsCancelling] = useState(false);
    // SSE indicator state. Starts in `connecting` because the EventSource is
    // opened in the same effect that mounts this view.
    const [sseStatus, setSseStatus] = useState<SseStatus>("connecting");
    const [lastEventTs, setLastEventTs] = useState<number | null>(null);

    useEffect(() => {
        if (
            initialStatus === "completed" ||
            initialStatus === "failed" ||
            initialStatus === "cancelled"
        ) {
            // Already terminal — no SSE channel to track.
            setSseStatus("disconnected");
            return;
        }

        const unsubscribe = codetourAPI.subscribeToTourStream(tourId, {
            onEvent: (type, data) => {
                if (type === "codetour.started") {
                    setStatus("running");
                } else if (type === "codetour.step_added") {
                    setSteps((prev) => [
                        ...prev,
                        {
                            index: data?.index ?? prev.length,
                            title: data?.title ?? "Step",
                            file: data?.file ?? "",
                            line: data?.line ?? 0,
                        },
                    ]);
                } else if (type === "codetour.step_rejected") {
                    setRejected((prev) => [
                        ...prev,
                        {
                            reason: data?.reason ?? "rejected",
                            title: data?.step?.title,
                            file: data?.step?.file,
                        },
                    ]);
                } else if (type === "codetour.completed") {
                    setStatus("completed");
                    // Refresh server-side to render the final viewer.
                    router.refresh();
                } else if (type === "codetour.failed") {
                    setStatus("failed");
                    setError(data?.error ?? "Unknown error");
                } else if (type === "codetour.cancelled") {
                    setStatus("cancelled");
                }
            },
            onSseState: (state) => {
                setSseStatus(state.status);
                setLastEventTs(state.lastEventTs);
            },
        });
        return unsubscribe;
    }, [tourId, initialStatus, router]);

    // Watchdog: drop to `disconnected` if no event/ping arrives within the
    // staleness window. Only meaningful while the underlying EventSource is
    // expected to be live (not for already-terminal initial statuses).
    useEffect(() => {
        if (sseStatus !== "connected") return;
        const id = setInterval(() => {
            if (
                lastEventTs &&
                Date.now() - lastEventTs > SSE_STALE_TIMEOUT_MS
            ) {
                setSseStatus("disconnected");
            }
        }, 1_000);
        return () => clearInterval(id);
    }, [sseStatus, lastEventTs]);

    async function onCancel() {
        setIsCancelling(true);
        try {
            await codetourAPI.cancelTour(tourId);
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setIsCancelling(false);
        }
    }

    const isLive = status === "pending" || status === "running";

    return (
        <div className="min-h-screen bg-background">
            <div className="border-b bg-card">
                <div className="container mx-auto px-4 py-4 flex items-center justify-between">
                    <div>
                        <h1 className="text-xl font-semibold">Code Tour</h1>
                        {initialQuery && (
                            <p className="text-sm text-muted-foreground">
                                {initialQuery}
                            </p>
                        )}
                    </div>
                    <div className="flex items-center gap-3">
                        <SseStatusIndicator
                            status={sseStatus}
                            lastEventTs={lastEventTs}
                        />
                        {isLive && (
                            <Button
                                variant="destructive"
                                size="sm"
                                onClick={onCancel}
                                disabled={isCancelling}
                            >
                                <Ban className="h-4 w-4 mr-1" />
                                {isCancelling ? "Cancelling…" : "Cancel"}
                            </Button>
                        )}
                    </div>
                </div>
            </div>

            <div className="container mx-auto px-4 py-8 max-w-3xl space-y-4">
                <Card className="p-6">
                    <StatusBanner status={status} error={error} />
                    {isLive && (
                        <div className="mt-4">
                            <p className="text-sm text-muted-foreground mb-2">
                                {steps.length}
                                {maxSteps ? ` / ${maxSteps}` : ""} steps written
                            </p>
                            <ul className="space-y-2">
                                {steps.map((s) => (
                                    <li
                                        key={`${s.index}-${s.file}-${s.line}`}
                                        className="flex items-start gap-2 text-sm"
                                    >
                                        <CheckCircle2 className="h-4 w-4 text-primary mt-0.5" />
                                        <div>
                                            <div className="font-medium">
                                                {s.title}
                                            </div>
                                            <div className="text-xs text-muted-foreground">
                                                {s.file}:{s.line}
                                            </div>
                                        </div>
                                    </li>
                                ))}
                                {steps.length === 0 && (
                                    <li className="text-sm text-muted-foreground italic">
                                        Waiting for the agent to discover the
                                        first step…
                                    </li>
                                )}
                            </ul>
                            {rejected.length > 0 && (
                                <details className="mt-4 text-xs text-muted-foreground">
                                    <summary>
                                        {rejected.length} rejected step(s)
                                    </summary>
                                    <ul className="mt-2 space-y-1">
                                        {rejected.map((r, i) => (
                                            <li
                                                key={i}
                                                className="flex items-start gap-2"
                                            >
                                                <XCircle className="h-3 w-3 mt-0.5 text-destructive" />
                                                <span>
                                                    {r.title ?? r.file ?? "step"}{" "}
                                                    — {r.reason}
                                                </span>
                                            </li>
                                        ))}
                                    </ul>
                                </details>
                            )}
                        </div>
                    )}
                </Card>
            </div>
        </div>
    );
}

function StatusBanner({
    status,
    error,
}: {
    status: LiveStatus;
    error: string | null;
}) {
    if (status === "pending") {
        return (
            <div className="flex items-center gap-2">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                <p className="text-sm">Tour queued — waiting for the worker…</p>
            </div>
        );
    }
    if (status === "running") {
        return (
            <div className="flex items-center gap-2">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                <p className="text-sm">
                    Generating tour… steps appear below as they're verified.
                </p>
            </div>
        );
    }
    if (status === "failed") {
        return (
            <div className="flex items-start gap-2 text-destructive">
                <AlertCircle className="h-5 w-5 mt-0.5" />
                <div>
                    <div className="font-medium">Tour failed</div>
                    {error && (
                        <div className="text-xs text-muted-foreground">
                            {error}
                        </div>
                    )}
                </div>
            </div>
        );
    }
    if (status === "cancelled") {
        return (
            <div className="flex items-center gap-2 text-muted-foreground">
                <Ban className="h-5 w-5" />
                <p className="text-sm">Tour cancelled.</p>
            </div>
        );
    }
    return null;
}
