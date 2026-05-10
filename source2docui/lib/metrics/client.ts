// Thin client around /api/gateway/metrics/aggregate.
//
// Returns the raw response shape (no remapping) so the dashboard page
// is the only place that knows about chart-vs-DTO field naming.

import type { GroupBy, MetricsAggregateResponse } from "./types";

export interface FetchAggregateOptions {
    from?: string | null;
    to?: string | null;
    groupBy: GroupBy;
    signal?: AbortSignal;
}

export async function fetchMetricsAggregate(
    opts: FetchAggregateOptions,
): Promise<MetricsAggregateResponse> {
    const params = new URLSearchParams();
    params.set("group_by", opts.groupBy);
    if (opts.from) params.set("from", opts.from);
    if (opts.to) params.set("to", opts.to);

    const response = await fetch(
        `/api/gateway/metrics/aggregate?${params.toString()}`,
        { signal: opts.signal, cache: "no-store" },
    );

    if (!response.ok) {
        throw new Error(
            `Metrics aggregate request failed: ${response.status} ${response.statusText}`,
        );
    }

    return (await response.json()) as MetricsAggregateResponse;
}
