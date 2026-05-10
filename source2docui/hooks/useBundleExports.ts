import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
    BundleExportArtifact,
    BundleExportArtifactListResponse,
} from "@/lib/bundles/schema";

export function useBundleExports(bundleId: number | null) {
    const [exports, setExports] = useState<BundleExportArtifact[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchExports = async () => {
        if (!bundleId) {
            setExports([]);
            return;
        }

        setLoading(true);
        setError(null);
        try {
            const response = await fetch(
                `/api/gateway/bundles/exports?bundle_id=${encodeURIComponent(String(bundleId))}`,
                {
                    cache: "no-store",
                },
            );

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || "Failed to fetch bundle exports");
            }

            const data: BundleExportArtifactListResponse = await response.json();
            setExports(data.exports || []);
        } catch (err) {
            const errorMessage =
                err instanceof Error ? err.message : "An error occurred";
            setError(errorMessage);
            toast.error(errorMessage);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        // auto-load when bundleId changes
        fetchExports();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bundleId]);

    return {
        exports,
        loading,
        error,
        refetch: fetchExports,
    };
}
