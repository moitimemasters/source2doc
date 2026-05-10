import { Suspense } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle, Loader2 } from "lucide-react";

import { CodeTourViewer } from "@/components/codetour/CodeTourViewer";
import { CodeTourStepContent } from "@/components/codetour/CodeTourStepContent";
import { TourLiveView } from "@/components/codetour/TourLiveView";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

// Short retry budget covers the race where the tour stream is created before
// the DB row is committed. Past that, treat 404 as "not found" so users do
// not stare at a blank skeleton for a minute on a stale link.
async function getTour(tourId: string, retries = 0, maxRetries = 4) {
    const response = await fetch(`${GATEWAY_URL}/api/v1/codetours/${tourId}`, {
        cache: "no-store",
    });

    if (!response.ok) {
        if (response.status === 404 && retries < maxRetries) {
            await new Promise((resolve) => setTimeout(resolve, 1500));
            return getTour(tourId, retries + 1, maxRetries);
        }
        return null;
    }

    return response.json();
}

function LoadingSkeleton() {
    return (
        <div className="min-h-screen bg-background">
            <div className="border-b bg-card">
                <div className="container mx-auto px-4 py-4">
                    <Skeleton className="h-8 w-64 mb-2" />
                    <Skeleton className="h-4 w-96" />
                </div>
            </div>

            <div className="container mx-auto px-4 py-8">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="space-y-4">
                        <Card className="p-6">
                            <div className="flex items-center gap-2 mb-4">
                                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                                <p className="text-sm text-muted-foreground">
                                    Loading tour...
                                </p>
                            </div>
                            <Skeleton className="h-6 w-3/4 mb-4" />
                            <Skeleton className="h-4 w-full mb-2" />
                            <Skeleton className="h-4 w-full mb-2" />
                            <Skeleton className="h-4 w-2/3" />
                        </Card>
                    </div>
                    <div className="space-y-4">
                        <Card className="p-6">
                            <Skeleton className="h-64 w-full" />
                        </Card>
                    </div>
                </div>
            </div>
        </div>
    );
}

async function TourContent({ tourId }: { tourId: string }) {
    const tour = await getTour(tourId);

    if (!tour) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                <Card className="p-6 max-w-md">
                    <div className="text-center">
                        <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
                        <h2 className="text-xl font-semibold mb-2">
                            Tour Not Found
                        </h2>
                        <p className="text-muted-foreground mb-4">
                            The tour generation may have failed or the tour does
                            not exist.
                        </p>
                    </div>
                </Card>
            </div>
        );
    }

    const status: string | undefined = tour.status;
    const liveQuery: string | undefined =
        tour.metadata?.query ?? tour.request_payload?.query;
    const maxSteps: number | undefined = tour.metadata?.max_steps;

    if (!status || !TERMINAL_STATUSES.has(status)) {
        return (
            <TourLiveView
                tourId={tourId}
                initialStatus={(status as any) ?? "pending"}
                initialQuery={liveQuery}
                maxSteps={maxSteps}
            />
        );
    }

    if (status !== "completed") {
        return (
            <TourLiveView
                tourId={tourId}
                initialStatus={status as any}
                initialQuery={liveQuery}
                maxSteps={maxSteps}
            />
        );
    }

    const codeBlocks = await Promise.all(
        tour.steps.map((step: any, idx: number) => (
            <CodeTourStepContent
                key={`${idx}-${step.title}`}
                step={step}
                stepIndex={idx}
                allSteps={tour.steps}
            />
        )),
    );

    return <CodeTourViewer tour={tour} codeBlocks={codeBlocks} />;
}

export default function TourPage({
    params,
}: {
    params: Promise<{ tourId: string }>;
}) {
    return (
        <Suspense fallback={<LoadingSkeleton />}>
            <TourContentWrapper params={params} />
        </Suspense>
    );
}

async function TourContentWrapper({
    params,
}: {
    params: Promise<{ tourId: string }>;
}) {
    const { tourId } = await params;
    return <TourContent tourId={tourId} />;
}

export function generateMetadata() {
    return {
        title: "Code Tour",
        description: "Interactive code tour",
    };
}
