// Wire format mirrored from core/gateway/app/routes/metrics/dto.py.
// Keep in sync if the DTO changes — there is no codegen step.

export type GroupBy = "day" | "model" | "step";

export interface MetricBucket {
    key: string;
    tokens: number;
    cost_usd: number | null;
    duration_ms_p50: number | null;
    duration_ms_p95: number | null;
    runs: number;
}

export interface MetricsAggregateResponse {
    group_by: GroupBy;
    buckets: MetricBucket[];
}
