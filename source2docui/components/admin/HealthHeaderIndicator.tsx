"use client";

import Link from "next/link";

import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
    classifyStatus,
    useHealthStatus,
    type ComponentStatus,
} from "@/lib/hooks/useHealthStatus";

const DOT_BY_STATUS: Record<ComponentStatus, string> = {
    ok: "bg-green-500 ring-green-500/30",
    error: "bg-red-500 ring-red-500/30",
    unknown: "bg-yellow-500 ring-yellow-500/30 animate-pulse",
};

const TOOLTIP_BY_STATUS: Record<ComponentStatus, string> = {
    ok: "All components operational",
    error: "Some components are degraded",
    unknown: "Health status pending",
};

/**
 * Tiny status dot rendered in the global header for admin routes. Clicking
 * it navigates to the full health dashboard. Polling lives in the shared
 * ``useHealthStatus`` hook, which (combined with the gateway's 5 s cache)
 * means the page and the header don't double-load workers.
 */
export function HealthHeaderIndicator() {
    const { data, worst, error } = useHealthStatus(15_000);

    // Build a compact tooltip listing the components that aren't ok.
    const failing = data
        ? Object.entries(data.components).filter(
              ([, value]) => classifyStatus(value) !== "ok",
          )
        : [];
    const tooltip = error
        ? `Health check failed: ${error}`
        : failing.length === 0
          ? TOOLTIP_BY_STATUS[worst]
          : `${TOOLTIP_BY_STATUS[worst]} — ${failing
                .map(([name]) => name)
                .join(", ")}`;

    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <Link
                    href="/admin/health"
                    aria-label={tooltip}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent"
                >
                    <span
                        className={cn(
                            "inline-block h-2.5 w-2.5 rounded-full ring-2",
                            DOT_BY_STATUS[worst],
                        )}
                        aria-hidden
                    />
                </Link>
            </TooltipTrigger>
            <TooltipContent side="bottom">{tooltip}</TooltipContent>
        </Tooltip>
    );
}
