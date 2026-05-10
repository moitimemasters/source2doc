"use client";

// Tokens-and-cost line chart for the over-time view.
//
// Two lines on the same X axis: tokens (left axis) and USD cost (right
// axis). Both axes use the theme's foreground/border CSS vars so the
// chart works in both light and dark mode without remounting on toggle.

import {
    CartesianGrid,
    Legend,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import type { MetricBucket } from "@/lib/metrics/types";

interface Props {
    buckets: MetricBucket[];
}

export function ByDayChart({ buckets }: Props) {
    // Recharts likes plain numbers; missing values become 0 for the
    // line geometry but we hide them in the tooltip via formatter.
    const data = buckets.map((b) => ({
        key: b.key,
        tokens: b.tokens,
        cost_usd: b.cost_usd ?? 0,
        runs: b.runs,
    }));

    return (
        <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid
                    stroke="var(--border)"
                    strokeDasharray="3 3"
                    vertical={false}
                />
                <XAxis
                    dataKey="key"
                    stroke="var(--muted-foreground)"
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                />
                <YAxis
                    yAxisId="tokens"
                    stroke="var(--muted-foreground)"
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                    width={64}
                    tickFormatter={(v: number) => formatCompact(v)}
                />
                <YAxis
                    yAxisId="cost"
                    orientation="right"
                    stroke="var(--muted-foreground)"
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                    width={64}
                    tickFormatter={(v: number) => `$${v.toFixed(2)}`}
                />
                <Tooltip
                    contentStyle={{
                        backgroundColor: "var(--popover)",
                        borderColor: "var(--border)",
                        color: "var(--popover-foreground)",
                        borderRadius: "8px",
                    }}
                    labelStyle={{ color: "var(--popover-foreground)" }}
                />
                <Legend
                    wrapperStyle={{ fontSize: 12, color: "var(--muted-foreground)" }}
                />
                <Line
                    yAxisId="tokens"
                    type="monotone"
                    dataKey="tokens"
                    name="Tokens"
                    stroke="var(--chart-1, #2563eb)"
                    strokeWidth={2}
                    dot={false}
                />
                <Line
                    yAxisId="cost"
                    type="monotone"
                    dataKey="cost_usd"
                    name="Cost (USD)"
                    stroke="var(--chart-2, #16a34a)"
                    strokeWidth={2}
                    dot={false}
                />
            </LineChart>
        </ResponsiveContainer>
    );
}

function formatCompact(n: number): string {
    if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
}
