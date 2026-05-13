"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
    Activity,
    AlertCircle,
    CheckCircle2,
    Clock,
    Loader2,
    XCircle,
} from "lucide-react";

import { codetourAPI, type CodetourInfo } from "@/lib/codetour-api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface TourHistoryListProps {
    initialTours: CodetourInfo[];
    pageSize: number;
}

const DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
});

function formatCreated(iso: string | null | undefined): string {
    if (!iso) return "—";
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return iso;
    return DATE_FORMATTER.format(t);
}

interface StatusConfig {
    label: string;
    icon: React.ReactNode;
    className: string;
}

function getStatusConfig(status: string | null | undefined): StatusConfig {
    switch (status) {
        case "completed":
            return {
                label: "completed",
                icon: <CheckCircle2 className="h-3 w-3 mr-1" />,
                className:
                    "bg-green-500/15 text-green-600 border-green-500/30 dark:text-green-400",
            };
        case "failed":
            return {
                label: "failed",
                icon: <XCircle className="h-3 w-3 mr-1" />,
                className:
                    "bg-destructive/15 text-destructive border-destructive/30",
            };
        case "cancelled":
            return {
                label: "cancelled",
                icon: <XCircle className="h-3 w-3 mr-1" />,
                className:
                    "bg-orange-500/15 text-orange-600 border-orange-500/30 dark:text-orange-400",
            };
        case "running":
            return {
                label: "running",
                icon: <Activity className="h-3 w-3 mr-1 animate-pulse" />,
                className:
                    "bg-blue-500/15 text-blue-600 border-blue-500/30 dark:text-blue-400",
            };
        case "pending":
            return {
                label: "pending",
                icon: <Clock className="h-3 w-3 mr-1" />,
                className: "",
            };
        default:
            return {
                label: status || "unknown",
                icon: null,
                className: "",
            };
    }
}

function deriveCardTitle(tour: CodetourInfo): string {
    if (tour.title && tour.title.trim()) {
        return tour.title.trim();
    }
    // CodetourInfo intentionally hides metadata.query, so fall back to
    // description if present, otherwise the tour id.
    if (tour.description && tour.description.trim()) {
        const desc = tour.description.trim();
        return desc.length > 80 ? `${desc.slice(0, 80)}…` : desc;
    }
    return tour.tour_id.slice(0, 8);
}

export function TourHistoryList({
    initialTours,
    pageSize,
}: TourHistoryListProps) {
    const [tours, setTours] = useState<CodetourInfo[]>(initialTours);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // If the initial server-side load returned a full page, more might exist.
    // We keep `hasMore` until a fetch returns less than `pageSize`.
    const [hasMore, setHasMore] = useState(initialTours.length >= pageSize);

    const offset = useMemo(() => tours.length, [tours.length]);

    async function handleLoadMore() {
        if (loadingMore) return;
        setLoadingMore(true);
        setError(null);
        try {
            const next = await codetourAPI.listAllTours(pageSize, offset);
            setTours((prev) => [...prev, ...next]);
            if (next.length < pageSize) {
                setHasMore(false);
            }
        } catch (err) {
            setError(
                err instanceof Error
                    ? err.message
                    : "Failed to load more tours",
            );
        } finally {
            setLoadingMore(false);
        }
    }

    if (tours.length === 0) {
        return (
            <Card className="p-10 text-center">
                <p className="text-muted-foreground">
                    No tours yet. Start one from a project wiki page.
                </p>
            </Card>
        );
    }

    return (
        <div className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {tours.map((tour) => {
                    const status = getStatusConfig(tour.status);
                    return (
                        <Link
                            key={tour.tour_id}
                            href={`/tour/${tour.tour_id}`}
                            className="group"
                        >
                            <Card className="h-full transition-all hover:shadow-lg hover:border-primary/50">
                                <CardHeader className="gap-2">
                                    <div className="flex items-start justify-between gap-2">
                                        <CardTitle className="text-sm leading-tight min-w-0 line-clamp-2 group-hover:text-primary transition-colors">
                                            {deriveCardTitle(tour)}
                                        </CardTitle>
                                        <Badge
                                            variant="outline"
                                            className={`flex-shrink-0 text-xs ${status.className}`}
                                        >
                                            {status.icon}
                                            {status.label}
                                        </Badge>
                                    </div>
                                </CardHeader>
                                <CardContent className="text-xs text-muted-foreground space-y-1">
                                    {tour.description && tour.title && (
                                        <p className="line-clamp-2">
                                            {tour.description}
                                        </p>
                                    )}
                                    <p>{formatCreated(tour.created_at)}</p>
                                    <p className="font-mono text-[10px] truncate">
                                        {tour.tour_id}
                                    </p>
                                </CardContent>
                            </Card>
                        </Link>
                    );
                })}
            </div>

            {error && (
                <div className="flex items-center gap-2 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    <span>{error}</span>
                </div>
            )}

            {hasMore && (
                <div className="flex justify-center">
                    <Button
                        variant="outline"
                        onClick={handleLoadMore}
                        disabled={loadingMore}
                    >
                        {loadingMore ? (
                            <>
                                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                Loading…
                            </>
                        ) : (
                            "Load more"
                        )}
                    </Button>
                </div>
            )}
        </div>
    );
}
