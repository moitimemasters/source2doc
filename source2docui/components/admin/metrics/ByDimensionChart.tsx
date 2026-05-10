"use client";

// Bar chart for the by-model and by-step sections. Single ``tokens``
// series; cost is surfaced in the tooltip but not as a separate axis to
// keep the visual simple.

import {
    Bar,
    BarChart,
    CartesianGrid,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import type { MetricBucket } from "@/lib/metrics/types";

interface Props {
    buckets: MetricBucket[];
}

export function ByDimensionChart({ buckets }: Props) {
    const data = buckets.map((b) => ({
        key: b.key,
        tokens: b.tokens,
        cost_usd: b.cost_usd,
        runs: b.runs,
    }));

    return (
        <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
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
                    interval={0}
                    angle={-15}
                    textAnchor="end"
                    height={50}
                />
                <YAxis
                    stroke="var(--muted-foreground)"
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                    width={64}
                    tickFormatter={(v: number) => formatCompact(v)}
                />
                <Tooltip
                    contentStyle={{
                        backgroundColor: "var(--popover)",
                        borderColor: "var(--border)",
                        color: "var(--popover-foreground)",
                        borderRadius: "8px",
                    }}
                    labelStyle={{ color: "var(--popover-foreground)" }}
                    formatter={(value, name, item) => {
                        if (name === "tokens") {
                            return [formatCompact(value as number), "Tokens"];
                        }
                        // Pass-through for the implicit cost/runs we add below.
                        return [String(value), String(name)];
                    }}
                />
                <Bar
                    dataKey="tokens"
                    name="tokens"
                    fill="var(--chart-1, #2563eb)"
                    radius={[6, 6, 0, 0]}
                />
            </BarChart>
        </ResponsiveContainer>
    );
}

function formatCompact(n: number): string {
    if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
}
