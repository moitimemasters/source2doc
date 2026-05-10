"use client";

import * as React from "react";

import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type SseStatus = "connecting" | "connected" | "disconnected";

interface SseStatusIndicatorProps {
    status: SseStatus;
    /** Epoch ms of the most recent event/ping, or null if none yet. */
    lastEventTs?: number | null;
    className?: string;
    /** Optional override for the visible text label. */
    label?: string;
}

const STATUS_META: Record<
    SseStatus,
    { dot: string; ring: string; label: string }
> = {
    connecting: {
        // Yellow with subtle pulse so it reads as transient, not error.
        dot: "bg-yellow-500 animate-pulse",
        ring: "ring-yellow-500/30",
        label: "Connecting",
    },
    connected: {
        dot: "bg-green-500",
        ring: "ring-green-500/30",
        label: "Connected",
    },
    disconnected: {
        dot: "bg-red-500",
        ring: "ring-red-500/30",
        label: "Disconnected",
    },
};

function formatRelativeAge(lastEventTs: number | null | undefined): string {
    if (!lastEventTs) return "no events yet";
    const deltaMs = Date.now() - lastEventTs;
    if (deltaMs < 1_000) return "just now";
    const seconds = Math.floor(deltaMs / 1_000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ago`;
}

/**
 * Compact SSE connection indicator. Shows an 8px dot + short label and a
 * tooltip with the last-event age. Re-renders once per second so the age
 * stays current without a global timer.
 */
export function SseStatusIndicator({
    status,
    lastEventTs,
    className,
    label,
}: SseStatusIndicatorProps) {
    // Mounted gate keeps SSR output deterministic — Date.now() in
    // formatRelativeAge would otherwise hydrate a different label than
    // the server rendered (React error #418).
    const [mounted, setMounted] = React.useState(false);
    const [, setTick] = React.useState(0);
    React.useEffect(() => {
        setMounted(true);
        const id = setInterval(() => setTick((n) => n + 1), 1_000);
        return () => clearInterval(id);
    }, []);

    const meta = STATUS_META[status];
    const visibleLabel = label ?? meta.label;
    const tooltip = mounted
        ? `SSE: ${meta.label} — last event ${formatRelativeAge(lastEventTs ?? null)}`
        : `SSE: ${meta.label}`;

    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <span
                    role="status"
                    aria-live="polite"
                    aria-label={tooltip}
                    className={cn(
                        "inline-flex items-center gap-1.5 text-xs text-muted-foreground select-none",
                        className,
                    )}
                >
                    <span
                        className={cn(
                            "inline-block h-2 w-2 rounded-full ring-2",
                            meta.dot,
                            meta.ring,
                        )}
                        aria-hidden
                    />
                    <span className="font-medium">{visibleLabel}</span>
                </span>
            </TooltipTrigger>
            <TooltipContent side="bottom">{tooltip}</TooltipContent>
        </Tooltip>
    );
}
