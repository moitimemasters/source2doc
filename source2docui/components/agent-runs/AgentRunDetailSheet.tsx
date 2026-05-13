"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";

import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "@/components/ui/sheet";
import { ThemedJsonView } from "@/components/ui/themed-json-view";
import type { AgentRunDetail, AgentRunSummary } from "./types";

interface AgentRunDetailSheetProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    run: AgentRunSummary | null;
}

/** Lazily fetches the full ``messages`` + ``output`` payload for one
 * ``agent_runs`` row. We don't preload because messages can run into
 * hundreds of KB per row — paying that cost up-front for the entire
 * table view would balloon the bundle size and slow scrolling. */
function useAgentRunDetail(runId: number | null) {
    const [detail, setDetail] = useState<AgentRunDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (runId == null) {
            setDetail(null);
            setError(null);
            return;
        }
        let cancelled = false;
        setLoading(true);
        setError(null);
        fetch(`/api/gateway/generations/agent-runs/${runId}`)
            .then(async (r) => {
                if (!r.ok) {
                    throw new Error(`Failed: ${r.status}`);
                }
                return (await r.json()) as AgentRunDetail;
            })
            .then((d) => {
                if (!cancelled) setDetail(d);
            })
            .catch((e: unknown) => {
                if (!cancelled) {
                    setError(e instanceof Error ? e.message : String(e));
                    setDetail(null);
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [runId]);

    return { detail, loading, error };
}

export function AgentRunDetailSheet({
    open,
    onOpenChange,
    run,
}: AgentRunDetailSheetProps) {
    const { detail, loading, error } = useAgentRunDetail(open ? run?.id ?? null : null);

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="w-full sm:max-w-3xl overflow-y-auto">
                <SheetHeader>
                    <SheetTitle>
                        {run?.agent_name ?? "Agent run"}
                        {run?.attempt && run.attempt > 1
                            ? ` · attempt ${run.attempt}`
                            : ""}
                    </SheetTitle>
                    <SheetDescription>
                        {run
                            ? [
                                  run.page_id && `page: ${run.page_id}`,
                                  run.section_id && `section: ${run.section_id}`,
                                  `id: ${run.id}`,
                              ]
                                  .filter(Boolean)
                                  .join(" · ")
                            : ""}
                    </SheetDescription>
                </SheetHeader>

                <div className="px-4 pb-6 space-y-4">
                    {run && (
                        <div className="rounded-md border border-border p-3 text-xs grid grid-cols-2 gap-y-1.5 gap-x-4 font-mono">
                            <div>
                                <span className="text-muted-foreground">started: </span>
                                {run.started_at}
                            </div>
                            <div>
                                <span className="text-muted-foreground">duration: </span>
                                {run.duration_ms != null
                                    ? `${run.duration_ms} ms`
                                    : "—"}
                            </div>
                            <div>
                                <span className="text-muted-foreground">success: </span>
                                <span
                                    className={
                                        run.success
                                            ? "text-green-600 dark:text-green-400"
                                            : "text-destructive"
                                    }
                                >
                                    {String(run.success)}
                                </span>
                            </div>
                            <div>
                                <span className="text-muted-foreground">requests: </span>
                                {run.request_count ?? "—"}
                            </div>
                            <div>
                                <span className="text-muted-foreground">input: </span>
                                {run.input_tokens ?? "—"}
                            </div>
                            <div>
                                <span className="text-muted-foreground">output: </span>
                                {run.output_tokens ?? "—"}
                            </div>
                            {run.cost_usd != null && (
                                <div className="col-span-2">
                                    <span className="text-muted-foreground">cost: </span>
                                    ${run.cost_usd.toFixed(6)}
                                </div>
                            )}
                            {run.error_type && (
                                <div className="col-span-2 text-destructive">
                                    {run.error_type}: {run.error_message}
                                </div>
                            )}
                        </div>
                    )}

                    {loading && (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Loading conversation…
                        </div>
                    )}

                    {error && (
                        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                            <div>{error}</div>
                        </div>
                    )}

                    {detail && (
                        <>
                            <section>
                                <h3 className="text-sm font-semibold mb-2">
                                    Messages
                                </h3>
                                <div className="rounded-md border border-border bg-muted/40 p-3 overflow-x-auto">
                                    <ThemedJsonView
                                        value={
                                            (detail.messages as object) ?? {}
                                        }
                                        collapsed={2}
                                        displayDataTypes={false}
                                        style={{ fontSize: "11px" }}
                                    />
                                </div>
                            </section>

                            {detail.output != null && (
                                <section>
                                    <h3 className="text-sm font-semibold mb-2">
                                        Output
                                    </h3>
                                    <div className="rounded-md border border-border bg-muted/40 p-3 overflow-x-auto">
                                        <ThemedJsonView
                                            value={
                                                typeof detail.output ===
                                                    "object" &&
                                                detail.output !== null
                                                    ? (detail.output as object)
                                                    : { value: detail.output }
                                            }
                                            collapsed={2}
                                            displayDataTypes={false}
                                            style={{ fontSize: "11px" }}
                                        />
                                    </div>
                                </section>
                            )}
                        </>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    );
}
