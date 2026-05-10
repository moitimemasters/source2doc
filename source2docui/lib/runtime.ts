"use client";

import { useEffect, useState } from "react";

export type RuntimeInfo = {
    default_preset: { name: string; description: string | null } | null;
    presets_count: number;
    configured: boolean;
};

export async function fetchRuntimeInfo(): Promise<RuntimeInfo | null> {
    try {
        const response = await fetch("/api/runtime/info", {
            cache: "no-store",
        });
        if (!response.ok) return null;
        return (await response.json()) as RuntimeInfo;
    } catch {
        return null;
    }
}

export function useRuntimeInfo() {
    const [info, setInfo] = useState<RuntimeInfo | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        fetchRuntimeInfo()
            .then((value) => {
                if (cancelled) return;
                setInfo(value);
            })
            .finally(() => {
                if (cancelled) return;
                setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    return { info, loading };
}
