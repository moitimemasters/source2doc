import { HealthDashboard } from "@/components/admin/HealthDashboard";

export const dynamic = "force-dynamic";

export default function AdminHealthPage() {
    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mx-auto max-w-6xl space-y-6">
                <div>
                    <h1 className="text-2xl font-semibold">Component health</h1>
                    <p className="text-muted-foreground">
                        Live status of the gateway, its dependencies (Postgres,
                        Redis, S3, Qdrant), and every worker. Polled every 15
                        seconds; gateway-side cache TTL is 5&nbsp;seconds.
                    </p>
                </div>
                <HealthDashboard />
            </div>
        </div>
    );
}
