"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Per-component health string returned by the gateway. ``"ok"`` means
 * healthy; anything else is treated as ``error``. The aggregate endpoint
 * surfaces failure detail via the prefix ``"error: <msg>"``.
 */
export type ComponentStatus = "ok" | "error" | "unknown";

export interface ComponentsHealth {
    components: Record<string, string>;
    checked_at: string;
}

export interface UseHealthStatusResult {
    /** Last successful payload or `null` until the first poll resolves. */
    data: ComponentsHealth | null;
    /** True while a poll is in flight (covers both first load and refresh). */
    loading: boolean;
    /** Last fetch error message, cleared on next success. */
    error: string | null;
    /** Worst observed component status across the latest payload. */
    worst: ComponentStatus;
    /** Force a refresh ahead of the next interval. */
    refetch: () => void;
}

const ENDPOINT = "/api/admin/health/components";

export function classifyStatus(raw: string | undefined): ComponentStatus {
    if (!raw) return "unknown";
    if (raw === "ok") return "ok";
    return "error";
}

function computeWorst(payload: ComponentsHealth | null): ComponentStatus {
    if (!payload) return "unknown";
    let worst: ComponentStatus = "ok";
    for (const value of Object.values(payload.components)) {
        const cls = classifyStatus(value);
        if (cls === "error") return "error"; // can't get worse than this
        if (cls === "unknown" && worst === "ok") worst = "unknown";
    }
    return worst;
}

/**
 * Polls ``/api/admin/health/components`` on a fixed interval (default 15s).
 *
 * The gateway already caches the underlying probe fan-out for 5 s so two
 * mounts of this hook (e.g. the page and the header widget) won't double
 * the load on workers.
 */
export function useHealthStatus(intervalMs: number = 15_000): UseHealthStatusResult {
    const [data, setData] = useState<ComponentsHealth | null>(null);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);

    // refetch trigger — bumping this forces the effect below to re-run.
    const [tick, setTick] = useState(0);
    const cancelledRef = useRef(false);

    useEffect(() => {
        cancelledRef.current = false;

        const fetchOnce = async () => {
            setLoading(true);
            try {
                const response = await fetch(ENDPOINT, {
                    method: "GET",
                    cache: "no-store",
                    credentials: "include",
                });
                if (!response.ok) {
                    throw new Error(
                        `health endpoint returned ${response.status}`,
                    );
                }
                const json = (await response.json()) as ComponentsHealth;
                if (!cancelledRef.current) {
                    setData(json);
                    setError(null);
                }
            } catch (err) {
                if (!cancelledRef.current) {
                    setError(
                        err instanceof Error ? err.message : "unknown error",
                    );
                }
            } finally {
                if (!cancelledRef.current) {
                    setLoading(false);
                }
            }
        };

        // First call kicks off immediately so the UI doesn't sit empty
        // for a full interval after mount.
        void fetchOnce();
        const handle = setInterval(() => {
            void fetchOnce();
        }, intervalMs);

        return () => {
            cancelledRef.current = true;
            clearInterval(handle);
        };
    }, [intervalMs, tick]);

    return {
        data,
        loading,
        error,
        worst: computeWorst(data),
        refetch: () => setTick((n) => n + 1),
    };
}
