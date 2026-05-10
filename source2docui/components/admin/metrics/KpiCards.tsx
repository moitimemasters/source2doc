// Four KPI cards above the charts: Total Tokens, Total $, Total Runs,
// Median Duration. ``null`` is rendered as an em dash so it's visually
// distinct from a real zero (e.g. "no priced models" vs "no usage at all").

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
    tokens: number;
    costUsd: number | null;
    runs: number;
    medianDurationMs: number | null;
}

export function KpiCards({ tokens, costUsd, runs, medianDurationMs }: Props) {
    return (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Kpi title="Total tokens" value={formatCompact(tokens)} />
            <Kpi
                title="Total cost (USD)"
                value={costUsd === null ? "—" : `$${costUsd.toFixed(2)}`}
            />
            <Kpi title="Agent steps" value={runs.toLocaleString()} />
            <Kpi
                title="Median duration"
                value={
                    medianDurationMs === null
                        ? "—"
                        : formatDuration(medianDurationMs)
                }
            />
        </div>
    );
}

function Kpi({ title, value }: { title: string; value: string }) {
    return (
        <Card>
            <CardHeader>
                <CardTitle className="text-sm font-medium text-muted-foreground">
                    {title}
                </CardTitle>
            </CardHeader>
            <CardContent>
                <p className="text-2xl font-bold">{value}</p>
            </CardContent>
        </Card>
    );
}

function formatCompact(n: number): string {
    if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return n.toLocaleString();
}

function formatDuration(ms: number): string {
    if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${ms}ms`;
}
