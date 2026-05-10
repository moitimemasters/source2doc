"use client";

import { useEffect, useState } from "react";

export interface BundleOption {
    id: number;
    generation_id: string;
    name: string | null;
    project_name: string | null;
    created_at?: string;
    pages_count?: number;
    failed_pages_count?: number;
    successful_pages_count?: number;
    repository?: {
        name?: string | null;
        git_url?: string | null;
        git_branch?: string | null;
    } | null;
}

interface BundlesResponse {
    bundles?: BundleOption[];
}

// Module-level dedupe so sibling components mounting on the same page don't
// each fire `/api/gateway/docs/bundles` independently. Cache lives 4s — long
// enough to merge a render burst, short enough that a navigation back to the
// page after work in another tab still picks up new rows.
let inflight: Promise<BundleOption[]> | null = null;
let cached: { at: number; bundles: BundleOption[] } | null = null;
const TTL_MS = 4000;

async function fetchBundles(): Promise<BundleOption[]> {
    const now = Date.now();
    if (cached && now - cached.at < TTL_MS) return cached.bundles;
    if (inflight) return inflight;

    inflight = (async () => {
        try {
            const res = await fetch("/api/gateway/docs/bundles?limit=200");
            if (!res.ok) throw new Error(`Gateway responded ${res.status}`);
            const data = (await res.json()) as BundlesResponse;
            const bundles = data.bundles ?? [];
            cached = { at: Date.now(), bundles };
            return bundles;
        } finally {
            inflight = null;
        }
    })();

    return inflight;
}

export function useBundlesList() {
    const [bundles, setBundles] = useState<BundleOption[]>(
        () => cached?.bundles ?? [],
    );
    const [loading, setLoading] = useState<boolean>(() => !cached);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        fetchBundles()
            .then((data) => {
                if (cancelled) return;
                setBundles(data);
                setError(null);
            })
            .catch((err: unknown) => {
                if (cancelled) return;
                setError(err instanceof Error ? err.message : "Failed to load");
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    return { bundles, loading, error };
}
