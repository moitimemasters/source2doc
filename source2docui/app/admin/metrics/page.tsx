// Admin metrics dashboard.
//
// Closes ТЗ items МНТ-06, МТР-01, МТР-02 (B3.4). Renders three sections
// over the gateway's /api/v1/metrics/aggregate endpoint:
//   * Tokens & Cost over time          (group_by=day,   line/bar)
//   * Tokens by Model                  (group_by=model, bar)
//   * Tokens by Step                   (group_by=step,  bar)
// plus four KPI cards at the top. Date range is synced to the URL via
// ``?from`` / ``?to`` so the dashboard is shareable.
//
// Client component: charts and the date filter rerun fetches without a
// page reload. The page is mounted with ``Suspense`` so ``useSearchParams``
// satisfies the App Router's static-prerender contract.
import { Suspense } from "react";

import { MetricsDashboard } from "@/components/admin/metrics/MetricsDashboard";

export const dynamic = "force-dynamic";

export default function AdminMetricsPage() {
    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mx-auto max-w-6xl">
                <div className="mb-6">
                    <h1 className="text-3xl font-bold">Metrics</h1>
                    <p className="text-muted-foreground">
                        Token usage, cost, and step latency across all generations.
                    </p>
                </div>
                <Suspense fallback={<div className="text-muted-foreground">Loading dashboard...</div>}>
                    <MetricsDashboard />
                </Suspense>
            </div>
        </div>
    );
}
