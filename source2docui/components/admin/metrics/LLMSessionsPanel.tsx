"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface SessionMember {
    token: string;
    worker_id: string;
    role: string;
    age_seconds: number;
    acquired_at_ms: number;
}

interface SessionEntry {
    api_key_hash: string;
    active: number;
    key_ttl_ms: number | null;
    members: SessionMember[];
}

interface SessionsResponse {
    sessions: SessionEntry[];
    scanned_at_ms: number;
}

const POLL_INTERVAL_MS = 5000;

export function LLMSessionsPanel() {
    const [data, setData] = useState<SessionsResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [lastFetched, setLastFetched] = useState<number | null>(null);

    const fetchOnce = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetch("/api/gateway/admin/llm-sessions", {
                method: "GET",
            });
            if (!response.ok) {
                throw new Error(`Gateway returned ${response.status}`);
            }
            const json = (await response.json()) as SessionsResponse;
            setData(json);
            setLastFetched(Date.now());
        } catch (err) {
            setError(err instanceof Error ? err.message : "Fetch failed");
        } finally {
            setLoading(false);
        }
    };

    // Poll on mount + every POLL_INTERVAL_MS so the table reflects
    // live lock churn without the user reloading. Not particularly
    // expensive — one ZRANGE per active key.
    useEffect(() => {
        fetchOnce();
        const handle = setInterval(fetchOnce, POLL_INTERVAL_MS);
        return () => clearInterval(handle);
    }, []);

    const totalActive = data?.sessions.reduce((s, e) => s + e.active, 0) ?? 0;
    const totalKeys = data?.sessions.length ?? 0;

    return (
        <Card>
            <CardHeader className="flex flex-row items-center justify-between">
                <div>
                    <CardTitle>LLM session locks</CardTitle>
                    <CardDescription>
                        Cluster-wide cap on parallel ``agent.run`` invocations,
                        keyed by ``sha256(api_key)[:16]``. Tokens carry the
                        worker process id and agent role so you can see who&apos;s
                        currently holding each slot. Polled every{" "}
                        {POLL_INTERVAL_MS / 1000}s.
                    </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                    {lastFetched && (
                        <span className="text-xs text-muted-foreground">
                            Updated {Math.round((Date.now() - lastFetched) / 1000)}s
                            ago
                        </span>
                    )}
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={fetchOnce}
                        disabled={loading}
                    >
                        {loading ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <RefreshCw className="h-4 w-4" />
                        )}
                        Refresh
                    </Button>
                </div>
            </CardHeader>
            <CardContent className="space-y-4">
                {error && (
                    <div className="rounded-lg border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
                        {error}
                    </div>
                )}
                <div className="text-sm text-muted-foreground">
                    {totalKeys === 0 ? (
                        <>No active session locks right now.</>
                    ) : (
                        <>
                            <span className="font-medium text-foreground">
                                {totalActive}
                            </span>{" "}
                            active session{totalActive === 1 ? "" : "s"} across{" "}
                            <span className="font-medium text-foreground">
                                {totalKeys}
                            </span>{" "}
                            api key{totalKeys === 1 ? "" : "s"}.
                        </>
                    )}
                </div>

                {data?.sessions.map((entry) => (
                    <div
                        key={entry.api_key_hash}
                        className="rounded-lg border border-border p-3"
                    >
                        <div className="flex items-center justify-between mb-2">
                            <div>
                                <code className="font-mono text-sm">
                                    {entry.api_key_hash}
                                </code>
                                <span className="ml-2 text-xs text-muted-foreground">
                                    sha256(api_key)[:16]
                                </span>
                            </div>
                            <div className="text-sm font-medium">
                                {entry.active} active
                            </div>
                        </div>
                        {entry.members.length === 0 ? (
                            <div className="text-xs text-muted-foreground">
                                No active holders (lock key exists but is drained).
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-xs">
                                    <thead>
                                        <tr className="text-left text-muted-foreground">
                                            <th className="py-1 pr-3">Worker</th>
                                            <th className="py-1 pr-3">Role</th>
                                            <th className="py-1 pr-3">Held for</th>
                                            <th className="py-1">Token nonce</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {entry.members.map((m) => (
                                            <tr
                                                key={m.token}
                                                className="border-t border-border"
                                            >
                                                <td className="py-1 pr-3 font-mono">
                                                    {m.worker_id || "—"}
                                                </td>
                                                <td className="py-1 pr-3">
                                                    {m.role || "—"}
                                                </td>
                                                <td className="py-1 pr-3">
                                                    {m.age_seconds.toFixed(1)}s
                                                </td>
                                                <td className="py-1 font-mono text-muted-foreground">
                                                    {m.token.split("|").pop()?.slice(0, 12)}
                                                    …
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                ))}
            </CardContent>
        </Card>
    );
}
