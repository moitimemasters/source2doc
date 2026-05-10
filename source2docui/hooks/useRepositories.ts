import { useState, useEffect } from "react";
import { toast } from "sonner";
import { RepositoryInfo, RepositoryListResponse } from "@/lib/repos/schema";

export function useRepositories() {
    const [repositories, setRepositories] = useState<RepositoryInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchRepositories = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetch("/api/gateway/repos", {
                cache: "no-store",
            });

            if (!response.ok) {
                throw new Error("Failed to fetch repositories");
            }

            const data: RepositoryListResponse = await response.json();
            setRepositories(data.repositories);
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
        fetchRepositories();
    }, []);

    return {
        repositories,
        loading,
        error,
        refetch: fetchRepositories,
    };
}
