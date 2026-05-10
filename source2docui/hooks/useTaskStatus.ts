import { useMemo } from "react";

import { useAppSelector } from "@/lib/store/hooks";
import type { StreamEvent, StreamInfo } from "@/lib/gateway/types";

export interface RepositoryInfoShort {
    name: string;
    source_type: string;
    git_url?: string | null;
    git_branch?: string | null;
}

export interface TaskStatus {
    generation_id: string;
    name?: string | null;
    description?: string | null;
    status: string;
    repo_id?: string | null;
    repository?: RepositoryInfoShort | null;
    started_at?: string | null;
    completed_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

function deriveStatusFromEvents(events: StreamEvent[]): string {
    if (events.some((e) => e.type === "generation.completed")) return "completed";
    if (events.some((e) => e.type === "step.failed")) return "failed";
    if (events.length > 0) return "running";
    return "pending";
}

function extractMetaFromEvents(events: StreamEvent[]): {
    name?: string | null;
    description?: string | null;
    repo_id?: string | null;
} {
    const requested = events.find((e) => e.type === "generation.requested");
    const data = (requested?.data || {}) as Record<string, unknown>;

    return {
        name: (data.name as string) || null,
        description: (data.description as string) || null,
        repo_id: (data.repo_id as string) || null,
    };
}

function extractMetaFromStreamInfo(info: StreamInfo | null | undefined): {
    name?: string | null;
    description?: string | null;
    status?: string | null;
    repo_id?: string | null;
    repository?: RepositoryInfoShort | null;
    created_at?: string | null;
    started_at?: string | null;
    completed_at?: string | null;
} {
    if (!info) return {};

    return {
        name: info.name ?? null,
        description: info.description ?? null,
        status: info.status ?? null,
        repo_id: info.repo_id ?? null,
        repository: (info.repository as RepositoryInfoShort | null | undefined) ?? null,
        created_at: info.created_at ?? null,
        started_at: info.started_at ?? null,
        completed_at: info.completed_at ?? null,
    };
}

export function useTaskStatus(generationId: string | null) {
    const events = useAppSelector((state) =>
        generationId ? state.streams.streams[generationId]?.events || [] : [],
    );

    const streamsListItem = useAppSelector((state) =>
        generationId
            ? state.streams.streamsList.find((s) => s.stream_id === generationId) ||
              null
            : null,
    );

    const { taskStatus, loading, error } = useMemo(() => {
        if (!generationId) {
            return { taskStatus: null, loading: false, error: null };
        }

        const fromList = extractMetaFromStreamInfo(streamsListItem);
        const fromEvents = extractMetaFromEvents(events);

        const name = fromList.name ?? fromEvents.name ?? null;
        const description = fromList.description ?? fromEvents.description ?? null;
        const repo_id = fromList.repo_id ?? fromEvents.repo_id ?? null;

        const status =
            fromList.status ||
            deriveStatusFromEvents(events);

        return {
            taskStatus: {
                generation_id: generationId,
                name,
                description,
                status,
                repo_id,
                repository: fromList.repository ?? null,
                created_at: fromList.created_at ?? null,
                started_at: fromList.started_at ?? null,
                completed_at: fromList.completed_at ?? null,
                updated_at: null,
            } satisfies TaskStatus,
            loading: false,
            error: null,
        };
    }, [events, generationId, streamsListItem]);

    return { taskStatus, loading, error };
}
