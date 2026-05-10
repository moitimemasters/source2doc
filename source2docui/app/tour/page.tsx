import { Suspense } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TourHistoryList } from "@/components/codetour/TourHistoryList";
import type { CodetourInfo } from "@/lib/codetour-api";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8003";

const PAGE_SIZE = 50;

async function fetchInitialTours(): Promise<CodetourInfo[]> {
    try {
        const response = await fetch(
            `${GATEWAY_URL}/api/v1/codetours?limit=${PAGE_SIZE}&offset=0`,
            { cache: "no-store" },
        );
        if (!response.ok) {
            return [];
        }
        const data = (await response.json()) as { tours?: CodetourInfo[] };
        return data.tours ?? [];
    } catch {
        return [];
    }
}

function HistorySkeleton() {
    return (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
                <Card key={i} className="p-4 space-y-3">
                    <Skeleton className="h-5 w-3/4" />
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-1/2" />
                </Card>
            ))}
        </div>
    );
}

async function HistoryContent() {
    const initialTours = await fetchInitialTours();
    return (
        <TourHistoryList
            initialTours={initialTours}
            pageSize={PAGE_SIZE}
        />
    );
}

export default function TourHistoryPage() {
    return (
        <main className="min-h-screen bg-gradient-to-b from-background to-muted/20">
            <div className="container mx-auto px-4 py-12">
                <div className="max-w-6xl mx-auto">
                    <div className="mb-8">
                        <h1 className="text-3xl font-bold tracking-tight">
                            Code Tours
                        </h1>
                        <p className="text-muted-foreground mt-2">
                            History of generated code tours.
                        </p>
                    </div>
                    <Suspense fallback={<HistorySkeleton />}>
                        <HistoryContent />
                    </Suspense>
                </div>
            </div>
        </main>
    );
}

export function generateMetadata() {
    return {
        title: "Code Tours",
        description: "History of generated code tours",
    };
}
