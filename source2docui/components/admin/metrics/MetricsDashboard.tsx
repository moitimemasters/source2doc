"use client";

// Top-level admin metrics dashboard.
//
// Closes ТЗ items МНТ-06, МТР-01, МТР-02 (B3.4). Renders three charts
// (over-time / by-model / by-step) plus four KPI cards. Date-range
// inputs sync to the URL via useSearchParams so a saved bookmark
// reproduces the same view.
//
// Empty state ("No data yet") is shown when the gateway returns
// ``buckets: []`` for all three queries — never zeroed bars.

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

import { fetchMetricsAggregate } from "@/lib/metrics/client";
import type {
    GroupBy,
    MetricBucket,
    MetricsAggregateResponse,
} from "@/lib/metrics/types";

import { ByDayChart } from "./ByDayChart";
import { ByDimensionChart } from "./ByDimensionChart";
import { KpiCards } from "./KpiCards";
import { LLMSessionsPanel } from "./LLMSessionsPanel";

// Default window: last 30 days. The DateRangePicker writes ISO strings
// into the URL; on first mount we seed the URL if both params are absent
// so a fresh visit doesn't fire a wide unbounded query.
const DEFAULT_DAYS = 30;

function defaultRange(): { from: string; to: string } {
    const to = new Date();
    const from = new Date(to.getTime() - DEFAULT_DAYS * 24 * 60 * 60 * 1000);
    // datetime-local inputs want "YYYY-MM-DDTHH:mm" without timezone;
    // we store the same shape in the URL so the round-trip is lossless.
    return {
        from: toLocalIso(from),
        to: toLocalIso(to),
    };
}

function toLocalIso(d: Date): string {
    const pad = (n: number) => String(n).padStart(2, "0");
    return (
        `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
        `T${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
}

interface AggregateState {
    data: MetricsAggregateResponse | null;
    loading: boolean;
    error: string | null;
}

const INITIAL: AggregateState = { data: null, loading: true, error: null };

function useAggregate(
    groupBy: GroupBy,
    from: string | null,
    to: string | null,
): AggregateState {
    const [state, setState] = useState<AggregateState>(INITIAL);

    useEffect(() => {
        const controller = new AbortController();
        setState((s) => ({ ...s, loading: true, error: null }));
        fetchMetricsAggregate({
            groupBy,
            from,
            to,
            signal: controller.signal,
        })
            .then((data) => setState({ data, loading: false, error: null }))
            .catch((err: unknown) => {
                if (err instanceof DOMException && err.name === "AbortError") {
                    return;
                }
                setState({
                    data: null,
                    loading: false,
                    error: err instanceof Error ? err.message : String(err),
                });
            });
        return () => controller.abort();
    }, [groupBy, from, to]);

    return state;
}

export function MetricsDashboard() {
    const router = useRouter();
    const searchParams = useSearchParams();

    const urlFrom = searchParams.get("from");
    const urlTo = searchParams.get("to");

    // Seed the URL with the default range so charts have a bounded query
    // on first visit. Empty range -> no rows -> empty-state.
    useEffect(() => {
        if (!urlFrom && !urlTo) {
            const { from, to } = defaultRange();
            const next = new URLSearchParams(searchParams.toString());
            next.set("from", from);
            next.set("to", to);
            router.replace(`?${next.toString()}`);
        }
        // We intentionally only run this on mount; subsequent param changes
        // are user-driven via the date inputs.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const fromIso = urlFrom ?? null;
    const toIso = urlTo ?? null;

    const dayState = useAggregate("day", fromIso, toIso);
    const modelState = useAggregate("model", fromIso, toIso);
    const stepState = useAggregate("step", fromIso, toIso);

    const allEmpty =
        dayState.data?.buckets.length === 0 &&
        modelState.data?.buckets.length === 0 &&
        stepState.data?.buckets.length === 0 &&
        !dayState.loading &&
        !modelState.loading &&
        !stepState.loading;

    const totals = useMemo(
        () => computeTotals(dayState.data?.buckets ?? []),
        [dayState.data],
    );

    const handleRangeChange = (from: string, to: string) => {
        const next = new URLSearchParams(searchParams.toString());
        if (from) next.set("from", from);
        else next.delete("from");
        if (to) next.set("to", to);
        else next.delete("to");
        router.replace(`?${next.toString()}`);
    };

    return (
        <div className="space-y-6">
            <DateRangeBar
                from={urlFrom ?? ""}
                to={urlTo ?? ""}
                onChange={handleRangeChange}
                onReset={() => {
                    const { from, to } = defaultRange();
                    handleRangeChange(from, to);
                }}
            />

            <KpiCards
                tokens={totals.tokens}
                costUsd={totals.costUsd}
                runs={totals.runs}
                medianDurationMs={totals.medianDurationMs}
            />

            {allEmpty ? (
                <EmptyState />
            ) : (
                <>
                    <Card>
                        <CardHeader>
                            <CardTitle>Tokens & Cost over time</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <ChartSection state={dayState}>
                                <ByDayChart buckets={dayState.data?.buckets ?? []} />
                            </ChartSection>
                        </CardContent>
                    </Card>

                    <div className="grid gap-6 md:grid-cols-2">
                        <Card>
                            <CardHeader>
                                <CardTitle>Tokens by Model</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <ChartSection state={modelState}>
                                    <ByDimensionChart
                                        buckets={modelState.data?.buckets ?? []}
                                    />
                                </ChartSection>
                            </CardContent>
                        </Card>

                        <Card>
                            <CardHeader>
                                <CardTitle>Tokens by Step</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <ChartSection state={stepState}>
                                    <ByDimensionChart
                                        buckets={stepState.data?.buckets ?? []}
                                    />
                                </ChartSection>
                            </CardContent>
                        </Card>
                    </div>
                </>
            )}

            {/* Live session-lock metrics are independent of the historical
                aggregate query above — they reflect what's running right now
                across the cluster, so render them even when the selected
                date range has no token data. */}
            <LLMSessionsPanel />
        </div>
    );
}

function ChartSection({
    state,
    children,
}: {
    state: AggregateState;
    children: React.ReactNode;
}) {
    if (state.loading && !state.data) {
        return (
            <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
                Loading...
            </div>
        );
    }
    if (state.error) {
        return (
            <div className="flex h-72 items-center justify-center text-sm text-destructive">
                {state.error}
            </div>
        );
    }
    if (!state.data || state.data.buckets.length === 0) {
        return (
            <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
                No data in this range.
            </div>
        );
    }
    return <div className="h-72 w-full">{children}</div>;
}

function EmptyState() {
    return (
        <Card>
            <CardContent className="flex flex-col items-center justify-center py-16 text-center">
                <p className="text-lg font-medium">No data yet</p>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    No generations recorded any token usage in the selected
                    date range. Run a generation, then come back — or widen
                    the range above.
                </p>
            </CardContent>
        </Card>
    );
}

function DateRangeBar({
    from,
    to,
    onChange,
    onReset,
}: {
    from: string;
    to: string;
    onChange: (from: string, to: string) => void;
    onReset: () => void;
}) {
    return (
        <Card>
            <CardContent className="flex flex-wrap items-end gap-4">
                <div>
                    <label
                        htmlFor="metrics-from"
                        className="mb-1 block text-xs font-medium text-muted-foreground"
                    >
                        From
                    </label>
                    <Input
                        id="metrics-from"
                        type="datetime-local"
                        value={from}
                        onChange={(e) => onChange(e.target.value, to)}
                    />
                </div>
                <div>
                    <label
                        htmlFor="metrics-to"
                        className="mb-1 block text-xs font-medium text-muted-foreground"
                    >
                        To
                    </label>
                    <Input
                        id="metrics-to"
                        type="datetime-local"
                        value={to}
                        onChange={(e) => onChange(from, e.target.value)}
                    />
                </div>
                <Button variant="outline" onClick={onReset}>
                    Last 30 days
                </Button>
            </CardContent>
        </Card>
    );
}

interface Totals {
    tokens: number;
    costUsd: number | null;
    runs: number;
    medianDurationMs: number | null;
}

function computeTotals(buckets: MetricBucket[]): Totals {
    if (buckets.length === 0) {
        return { tokens: 0, costUsd: null, runs: 0, medianDurationMs: null };
    }

    let tokens = 0;
    let runs = 0;
    let costSum = 0;
    let costSeen = false;
    const p50s: number[] = [];

    for (const b of buckets) {
        tokens += b.tokens;
        runs += b.runs;
        if (b.cost_usd !== null) {
            costSum += b.cost_usd;
            costSeen = true;
        }
        if (b.duration_ms_p50 !== null) p50s.push(b.duration_ms_p50);
    }

    // "Median duration" KPI: median of per-day p50s. This is an
    // approximation (true global median needs raw rows), but it's the
    // right granularity for the dashboard.
    p50s.sort((a, b) => a - b);
    const median =
        p50s.length === 0
            ? null
            : p50s.length % 2 === 1
              ? p50s[(p50s.length - 1) / 2]
              : Math.round((p50s[p50s.length / 2 - 1] + p50s[p50s.length / 2]) / 2);

    return {
        tokens,
        costUsd: costSeen ? costSum : null,
        runs,
        medianDurationMs: median,
    };
}
