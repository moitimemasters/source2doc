"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { AgentRunDetailSheet } from "./AgentRunDetailSheet";
import type { AgentRunSummary, AgentRunsResponse } from "./types";

interface AgentRunsTableProps {
    generationId: string;
}

const AGENT_BADGE_VARIANT: Record<
    string,
    "default" | "secondary" | "destructive" | "outline"
> = {
    planner: "default",
    subplanner: "secondary",
    writer: "outline",
    critic: "secondary",
    diagrammer: "outline",
};

function formatDuration(ms: number | null): string {
    if (ms == null) return "—";
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
}

function formatTokens(n: number | null): string {
    if (n == null) return "—";
    return n.toLocaleString();
}

function formatTime(iso: string): string {
    try {
        return new Date(iso).toLocaleTimeString();
    } catch {
        return iso;
    }
}

export function AgentRunsTable({ generationId }: AgentRunsTableProps) {
    const [runs, setRuns] = useState<AgentRunSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [selected, setSelected] = useState<AgentRunSummary | null>(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);
        fetch(`/api/gateway/generations/${generationId}/agent-runs`)
            .then(async (r) => {
                if (!r.ok) {
                    throw new Error(`Failed: ${r.status}`);
                }
                return (await r.json()) as AgentRunsResponse;
            })
            .then((d) => {
                if (!cancelled) setRuns(d.items);
            })
            .catch((e: unknown) => {
                if (!cancelled) {
                    setError(e instanceof Error ? e.message : String(e));
                    setRuns([]);
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [generationId]);

    if (loading) {
        return (
            <div className="text-sm text-muted-foreground py-8 text-center">
                Loading agent runs…
            </div>
        );
    }

    if (error) {
        return (
            <div className="text-sm text-destructive py-8 text-center">
                {error}
            </div>
        );
    }

    if (runs.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                No agent runs recorded for this generation yet.
            </div>
        );
    }

    return (
        <>
            <div className="rounded-md border border-border overflow-hidden">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[80px]">Status</TableHead>
                            <TableHead>Agent</TableHead>
                            <TableHead>Page</TableHead>
                            <TableHead>Section</TableHead>
                            <TableHead className="text-right">Attempt</TableHead>
                            <TableHead className="text-right">Duration</TableHead>
                            <TableHead className="text-right">Reqs</TableHead>
                            <TableHead className="text-right">In</TableHead>
                            <TableHead className="text-right">Out</TableHead>
                            <TableHead className="text-right">Cost</TableHead>
                            <TableHead>Started</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {runs.map((run) => {
                            const variant =
                                AGENT_BADGE_VARIANT[run.agent_name] ?? "outline";
                            return (
                                <TableRow
                                    key={run.id}
                                    onClick={() => setSelected(run)}
                                    className="cursor-pointer hover:bg-muted/50"
                                >
                                    <TableCell>
                                        {run.success ? (
                                            <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                                        ) : (
                                            <XCircle
                                                className="h-4 w-4 text-destructive"
                                                aria-label={
                                                    run.error_type ?? "failed"
                                                }
                                            />
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <Badge variant={variant}>
                                            {run.agent_name}
                                        </Badge>
                                    </TableCell>
                                    <TableCell className="font-mono text-xs">
                                        {run.page_id ?? "—"}
                                    </TableCell>
                                    <TableCell className="font-mono text-xs">
                                        {run.section_id ?? "—"}
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-xs">
                                        {run.attempt}
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-xs">
                                        {formatDuration(run.duration_ms)}
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-xs">
                                        {run.request_count ?? "—"}
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-xs">
                                        {formatTokens(run.input_tokens)}
                                    </TableCell>
                                    <TableCell className="text-right font-mono text-xs">
                                        {formatTokens(run.output_tokens)}
                                    </TableCell>
                                    <TableCell
                                        className={cn(
                                            "text-right font-mono text-xs",
                                            run.cost_usd == null &&
                                                "text-muted-foreground",
                                        )}
                                    >
                                        {run.cost_usd != null
                                            ? `$${run.cost_usd.toFixed(4)}`
                                            : "—"}
                                    </TableCell>
                                    <TableCell className="font-mono text-xs text-muted-foreground">
                                        {formatTime(run.started_at)}
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </div>

            <AgentRunDetailSheet
                open={selected != null}
                onOpenChange={(o) => {
                    if (!o) setSelected(null);
                }}
                run={selected}
            />
        </>
    );
}
