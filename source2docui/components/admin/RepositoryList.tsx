"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useRepositories } from "@/hooks/useRepositories";
import { RepositoryListView } from "./RepositoryListView";

interface RepositoryListProps {
    bindRefetch?: (fn: () => void) => void;
}

export function RepositoryList({ bindRefetch }: RepositoryListProps = {}) {
    const { repositories, loading, error, refetch } = useRepositories();

    useEffect(() => {
        bindRefetch?.(refetch);
    }, [bindRefetch, refetch]);

    const [copiedId, setCopiedId] = useState<string | null>(null);
    const [deletingId, setDeletingId] = useState<string | null>(null);

    const handleCopy = async (repoId: string) => {
        try {
            await navigator.clipboard.writeText(repoId);
            setCopiedId(repoId);
            toast.success("Repository ID copied to clipboard");
            setTimeout(() => setCopiedId(null), 2000);
        } catch {
            toast.error("Failed to copy to clipboard");
        }
    };

    const handleDelete = async (repoId: string, repoName: string) => {
        if (
            !window.confirm(
                `Delete repository "${repoName}"?\n\nThis removes the row from Postgres and the archive from S3. Streams referencing it will become orphaned.`,
            )
        ) {
            return;
        }
        setDeletingId(repoId);
        try {
            const res = await fetch(
                `/api/gateway/repos/${encodeURIComponent(repoId)}`,
                { method: "DELETE" },
            );
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.detail || `Gateway returned ${res.status}`);
            }
            toast.success(`Deleted ${repoName}`);
            refetch();
        } catch (err) {
            toast.error(
                err instanceof Error ? err.message : "Failed to delete repository",
            );
        } finally {
            setDeletingId(null);
        }
    };

    return (
        <RepositoryListView
            repositories={repositories}
            loading={loading}
            error={error}
            copiedId={copiedId}
            deletingId={deletingId}
            onRefresh={refetch}
            onCopy={handleCopy}
            onDelete={handleDelete}
        />
    );
}
