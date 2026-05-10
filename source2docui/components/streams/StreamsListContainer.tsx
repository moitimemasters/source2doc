"use client";

import { useEffect } from "react";
import { useAppDispatch, useAppSelector } from "@/lib/store/hooks";
import { fetchStreamsList } from "@/lib/store/streams-slice";
import { StreamsHeader } from "./StreamsHeader";
import { StreamsGrid } from "./StreamsGrid";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";

const TERMINAL_STATUSES = new Set(["completed", "failed", "timeout", "cancelled"]);

export function StreamsListContainer() {
    const dispatch = useAppDispatch();
    const { streamsList, isLoadingList, listError } = useAppSelector(
        (state) => state.streams
    );

    const hasActive =
        streamsList.length === 0 ||
        streamsList.some((s) => !TERMINAL_STATUSES.has(s.status ?? ""));

    useEffect(() => {
        dispatch(fetchStreamsList());
    }, [dispatch]);

    useEffect(() => {
        // Only poll while at least one stream is still active. Once everything
        // is terminal there is nothing to refresh, so we drop the request loop
        // until a manual reload or new stream appears.
        if (!hasActive) return;
        const interval = setInterval(() => {
            dispatch(fetchStreamsList());
        }, 5000);
        return () => clearInterval(interval);
    }, [dispatch, hasActive]);

    if (listError) {
        return <ErrorState error={listError} />;
    }

    return (
        <main className="min-h-screen bg-gradient-to-b from-background to-muted/20">
            <div className="container mx-auto px-4 py-16">
                <div className="max-w-6xl mx-auto">
                    <StreamsHeader streams={streamsList} />

                    {isLoadingList && streamsList.length === 0 ? (
                        <EmptyState isLoading={true} />
                    ) : streamsList.length === 0 ? (
                        <EmptyState isLoading={false} />
                    ) : (
                        <StreamsGrid streams={streamsList} />
                    )}
                </div>
            </div>
        </main>
    );
}
