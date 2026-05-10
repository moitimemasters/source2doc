"use client";

import Link from "next/link";
import {
    Card,
    CardHeader,
    CardTitle,
    CardDescription,
    CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
    Activity,
    CheckCircle2,
    XCircle,
    Clock,
    CircleStop,
    FileText,
    GitBranch,
    Upload,
    Calendar,
    Timer,
} from "lucide-react";
import { StreamInfo } from "@/lib/gateway/types";

interface StreamCardProps {
    stream: StreamInfo;
}

type StreamStatus =
    | "pending"
    | "running"
    | "completed"
    | "failed"
    | "stopped"
    | "timeout"
    | "unknown";

function getStatusConfig(status: string | null | undefined): {
    label: string;
    variant: "default" | "secondary" | "destructive" | "outline";
    icon: React.ReactNode;
    className: string;
} {
    switch (status as StreamStatus) {
        case "running":
            return {
                label: "Running",
                variant: "default",
                icon: <Activity className="h-3 w-3 mr-1 animate-pulse" />,
                className: "bg-blue-500/15 text-blue-600 border-blue-500/30 dark:text-blue-400",
            };
        case "completed":
            return {
                label: "Done",
                variant: "outline",
                icon: <CheckCircle2 className="h-3 w-3 mr-1" />,
                className: "bg-green-500/15 text-green-600 border-green-500/30 dark:text-green-400",
            };
        case "failed":
            return {
                label: "Failed",
                variant: "destructive",
                icon: <XCircle className="h-3 w-3 mr-1" />,
                className: "",
            };
        case "stopped":
            return {
                label: "Stopped",
                variant: "outline",
                icon: <CircleStop className="h-3 w-3 mr-1" />,
                className:
                    "bg-amber-500/15 text-amber-600 border-amber-500/30 dark:text-amber-400",
            };
        case "timeout":
            return {
                label: "Timeout",
                variant: "outline",
                icon: <XCircle className="h-3 w-3 mr-1" />,
                className: "bg-orange-500/15 text-orange-600 border-orange-500/30 dark:text-orange-400",
            };
        case "pending":
            return {
                label: "Pending",
                variant: "secondary",
                icon: <Clock className="h-3 w-3 mr-1" />,
                className: "",
            };
        default:
            return {
                label: "Active",
                variant: "secondary",
                icon: <Activity className="h-3 w-3 mr-1" />,
                className: "",
            };
    }
}

function formatTimestamp(iso: string | null | undefined): string | null {
    if (!iso) return null;
    try {
        // undefined locale = browser default, so the date format matches the
        // viewer's region instead of being hardcoded to ru-RU.
        return new Date(iso).toLocaleString(undefined, {
            day: "2-digit",
            month: "2-digit",
            year: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return null;
    }
}

function formatDuration(
    start: string | null | undefined,
    end: string | null | undefined,
    isActive: boolean,
): string | null {
    if (!start) return null;
    // Only fall back to "now" while the stream is still running. A terminal
    // stream without a completed_at timestamp would otherwise tick forever
    // every time the parent re-renders.
    if (!end && !isActive) return null;
    const startMs = new Date(start).getTime();
    const endMs = end ? new Date(end).getTime() : Date.now();
    const diffSec = Math.floor((endMs - startMs) / 1000);
    if (diffSec < 60) return `${diffSec}s`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ${diffSec % 60}s`;
    return `${Math.floor(diffMin / 60)}h ${diffMin % 60}m`;
}

export function StreamCard({ stream }: StreamCardProps) {
    const statusConfig = getStatusConfig(stream.status);
    const displayName = stream.name || null;
    const createdAt = formatTimestamp(stream.created_at);
    const isActive = stream.status === "running" || stream.status === "pending";
    const duration = formatDuration(
        stream.started_at || stream.created_at,
        stream.completed_at,
        isActive,
    );

    return (
        <Link href={`/streams/${stream.stream_id}`} className="group">
            <Card className="h-full transition-all hover:shadow-lg hover:border-primary/50">
                <CardHeader className="pb-2 gap-2">
                    <div className="flex items-start justify-between gap-2">
                        <CardTitle
                            className={`group-hover:text-primary transition-colors text-sm leading-tight min-w-0 truncate ${
                                displayName ? "" : "font-mono"
                            }`}
                        >
                            {displayName ?? `${stream.stream_id.slice(0, 16)}…`}
                        </CardTitle>
                        <Badge
                            variant={statusConfig.variant}
                            className={`flex-shrink-0 text-xs ${statusConfig.className}`}
                        >
                            {statusConfig.icon}
                            {statusConfig.label}
                        </Badge>
                    </div>

                    {stream.repository ? (
                        <CardDescription className="flex items-center gap-1.5 text-xs min-w-0">
                            {stream.repository.source_type === "git" ? (
                                <GitBranch className="h-3.5 w-3.5 flex-shrink-0" />
                            ) : (
                                <Upload className="h-3.5 w-3.5 flex-shrink-0" />
                            )}
                            <span className="truncate">
                                {stream.repository.git_url ||
                                    stream.repository.name}
                            </span>
                        </CardDescription>
                    ) : (
                        <CardDescription className="font-mono text-xs truncate">
                            {stream.stream_id}
                        </CardDescription>
                    )}
                </CardHeader>

                <CardContent className="pt-0">
                    <div className="grid grid-cols-[auto,1fr] gap-x-2 gap-y-1.5 text-xs text-muted-foreground items-center">
                        <FileText className="h-3.5 w-3.5" aria-hidden />
                        <span>{stream.event_count} events</span>

                        {createdAt && (
                            <>
                                <Calendar className="h-3.5 w-3.5" aria-hidden />
                                <span className="truncate">{createdAt}</span>
                            </>
                        )}

                        {duration && (
                            <>
                                <Timer className="h-3.5 w-3.5" aria-hidden />
                                <span>
                                    {isActive ? "Running for " : "Took "}
                                    {duration}
                                </span>
                            </>
                        )}
                    </div>

                    {displayName && (
                        <div className="text-[11px] font-mono text-muted-foreground truncate pt-2 mt-2 border-t border-border/40">
                            {stream.stream_id}
                        </div>
                    )}
                </CardContent>
            </Card>
        </Link>
    );
}
