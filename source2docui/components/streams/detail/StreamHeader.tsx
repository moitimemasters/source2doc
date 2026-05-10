"use client";

import Link from "next/link";
import { ArrowLeft, GitBranch, MessagesSquare, Terminal, Upload } from "lucide-react";
import { ProgressBar } from "./ProgressBar";
import { useTaskStatus } from "@/hooks/useTaskStatus";
import { useSseStatus } from "@/hooks/useSseStatus";
import { SseStatusIndicator } from "@/components/sse-status-indicator";
import { useAppSelector } from "@/lib/store/hooks";

interface StreamHeaderProps {
    streamId: string;
    overallProgress: number | null;
}

export function StreamHeader({ streamId, overallProgress }: StreamHeaderProps) {
    const { taskStatus } = useTaskStatus(streamId);
    const { status: sseStatus, lastEventTs } = useSseStatus(streamId);
    const traceId = useAppSelector(
        (state) => state.streams.streams[streamId]?.traceId ?? null,
    );

    const displayName =
        taskStatus?.name ||
        taskStatus?.repository?.name ||
        null;

    return (
        <div className="mb-8">
            <Link
                href="/streams"
                className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground mb-4"
            >
                <ArrowLeft className="h-4 w-4 mr-1" />
                Back to Streams
            </Link>

            <div className="flex items-start justify-between mb-6">
                <div className="flex-1 min-w-0 mr-4">
                    <h1 className="text-3xl font-bold tracking-tight mb-1">
                        {displayName || "Stream Monitor"}
                    </h1>
                    {displayName && taskStatus?.repository && (
                        <div className="flex items-center gap-1.5 text-sm text-muted-foreground mb-1">
                            {taskStatus.repository.source_type === "git" ? (
                                <GitBranch className="h-3.5 w-3.5 flex-shrink-0" />
                            ) : (
                                <Upload className="h-3.5 w-3.5 flex-shrink-0" />
                            )}
                            <span className="truncate">
                                {taskStatus.repository.git_url ||
                                    taskStatus.repository.name}
                                {taskStatus.repository.git_branch && (
                                    <span className="ml-1 text-primary">
                                        @{taskStatus.repository.git_branch}
                                    </span>
                                )}
                            </span>
                        </div>
                    )}
                    {taskStatus?.description && (
                        <p className="text-sm text-muted-foreground mb-1">
                            {taskStatus.description}
                        </p>
                    )}
                    <p className="text-muted-foreground font-mono text-xs">
                        {streamId}
                    </p>
                    {traceId && (
                        <p
                            className="text-xs text-muted-foreground font-mono"
                            title="Trace ID"
                        >
                            trace: {traceId}
                        </p>
                    )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                    <Link
                        href={`/streams/${streamId}/logs`}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-secondary text-xs font-mono text-secondary-foreground/70 hover:text-secondary-foreground hover:border-border/80 transition-colors"
                    >
                        <Terminal className="h-3 w-3" />
                        logs
                    </Link>
                    <Link
                        href={`/streams/${streamId}/agent-runs`}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-border bg-secondary text-xs font-mono text-secondary-foreground/70 hover:text-secondary-foreground hover:border-border/80 transition-colors"
                    >
                        <MessagesSquare className="h-3 w-3" />
                        agent runs
                    </Link>
                    <SseStatusIndicator
                        status={sseStatus}
                        lastEventTs={lastEventTs}
                    />
                </div>
            </div>

            {overallProgress !== null && (
                <ProgressBar
                    progress={overallProgress}
                    label="Overall Progress"
                />
            )}
        </div>
    );
}
