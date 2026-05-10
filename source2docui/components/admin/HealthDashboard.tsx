"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
    classifyStatus,
    useHealthStatus,
    type ComponentStatus,
} from "@/lib/hooks/useHealthStatus";

const COMPONENT_LABELS: Record<string, string> = {
    postgres: "PostgreSQL",
    redis: "Redis",
    s3: "S3 / LocalStack",
    qdrant: "Qdrant",
    "worker-docgen": "Worker — docgen",
    "worker-repos": "Worker — repos",
    "worker-bundler": "Worker — bundler",
    "worker-codetour": "Worker — codetour",
};

// Reuse the SseStatusIndicator palette (green-500 / yellow-500 / red-500).
const DOT_BY_STATUS: Record<ComponentStatus, string> = {
    ok: "bg-green-500 ring-green-500/30",
    error: "bg-red-500 ring-red-500/30",
    unknown: "bg-yellow-500 ring-yellow-500/30",
};

const STATUS_LABEL: Record<ComponentStatus, string> = {
    ok: "Operational",
    error: "Degraded",
    unknown: "Unknown",
};

function formatChecked(iso: string | undefined): string {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleTimeString();
    } catch {
        return iso;
    }
}

interface HealthCardProps {
    name: string;
    rawStatus: string;
    checkedAt: string | undefined;
}

function HealthCard({ name, rawStatus, checkedAt }: HealthCardProps) {
    const status = classifyStatus(rawStatus);
    const label = COMPONENT_LABELS[name] ?? name;
    const detail =
        status === "ok"
            ? STATUS_LABEL.ok
            : (rawStatus.startsWith("error: ")
                  ? rawStatus.slice("error: ".length)
                  : rawStatus) || STATUS_LABEL.error;

    return (
        <Card className="h-full">
            <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{label}</CardTitle>
                <span
                    aria-label={STATUS_LABEL[status]}
                    className={cn(
                        "mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full ring-2",
                        DOT_BY_STATUS[status],
                    )}
                />
            </CardHeader>
            <CardContent className="space-y-1">
                <p
                    className={cn(
                        "text-sm font-semibold",
                        status === "ok" && "text-green-600 dark:text-green-400",
                        status === "error" && "text-red-600 dark:text-red-400",
                        status === "unknown" &&
                            "text-yellow-600 dark:text-yellow-400",
                    )}
                >
                    {STATUS_LABEL[status]}
                </p>
                {status !== "ok" && (
                    <p
                        className="text-xs text-muted-foreground break-words"
                        title={rawStatus}
                    >
                        {detail}
                    </p>
                )}
                <p className="text-xs text-muted-foreground">
                    Checked at {formatChecked(checkedAt)}
                </p>
            </CardContent>
        </Card>
    );
}

export function HealthDashboard() {
    const { data, loading, error, worst, refetch } = useHealthStatus(15_000);

    const hasData = data !== null;
    const components = data?.components ?? {};
    const checkedAt = data?.checked_at;

    const banner =
        worst === "ok"
            ? {
                  text: "All systems operational",
                  className:
                      "bg-green-500/10 text-green-700 dark:text-green-300 border-green-500/40",
              }
            : worst === "error"
              ? {
                    text: "Some components are degraded",
                    className:
                        "bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/40",
                }
              : {
                    text: "Status unknown — waiting for first probe",
                    className:
                        "bg-yellow-500/10 text-yellow-700 dark:text-yellow-300 border-yellow-500/40",
                };

    return (
        <div className="space-y-6">
            <div
                role="status"
                aria-live="polite"
                className={cn(
                    "flex items-center justify-between gap-4 rounded-lg border px-4 py-3",
                    banner.className,
                )}
            >
                <div className="flex items-center gap-3">
                    <span
                        className={cn(
                            "inline-block h-3 w-3 rounded-full ring-2",
                            DOT_BY_STATUS[worst],
                        )}
                        aria-hidden
                    />
                    <span className="font-medium">{banner.text}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    {loading && hasData && <span>Refreshing…</span>}
                    {!loading && checkedAt && (
                        <span>Last update {formatChecked(checkedAt)}</span>
                    )}
                    <button
                        type="button"
                        onClick={refetch}
                        className="rounded border px-2 py-1 text-xs hover:bg-background"
                    >
                        Refresh
                    </button>
                </div>
            </div>

            {error && (
                <div className="rounded-md border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">
                    Failed to fetch health status: {error}
                </div>
            )}

            {!hasData && !error && loading && (
                <p className="text-sm text-muted-foreground">
                    Loading component health…
                </p>
            )}

            {hasData && (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    {Object.entries(components).map(([name, value]) => (
                        <HealthCard
                            key={name}
                            name={name}
                            rawStatus={value}
                            checkedAt={checkedAt}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
