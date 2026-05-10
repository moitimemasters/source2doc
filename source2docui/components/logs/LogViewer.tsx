"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useVirtualizer } from "@tanstack/react-virtual";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";

export interface LogEntry {
    id: string;
    level: string;
    event: string;
    timestamp: string;
    logger: string;
    extras?: string | null;
}

type LogEntryWithSeq = LogEntry & { __seq: number };

interface LogViewerProps {
    generationId: string;
    className?: string;
}

const LEVEL_COLORS: Record<string, string> = {
    debug: "text-muted-foreground",
    info: "text-sky-600 dark:text-sky-400",
    warning: "text-amber-600 dark:text-amber-400",
    warn: "text-amber-600 dark:text-amber-400",
    error: "text-red-600 dark:text-red-400",
    critical: "text-red-700 dark:text-red-500",
};

const LEVEL_LABELS: Record<string, string> = {
    debug: "DBG",
    info: "INF",
    warning: "WRN",
    warn: "WRN",
    error: "ERR",
    critical: "CRT",
};

function levelColor(level: string): string {
    return LEVEL_COLORS[level.toLowerCase()] ?? "text-muted-foreground";
}

function levelLabel(level: string): string {
    return (
        LEVEL_LABELS[level.toLowerCase()] ??
        level.toUpperCase().slice(0, 3)
    );
}

function formatTimestamp(ts: string): string {
    if (!ts) return "";
    try {
        const d = new Date(ts);
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        const ss = String(d.getSeconds()).padStart(2, "0");
        const ms = String(d.getMilliseconds()).padStart(3, "0");
        return `${hh}:${mm}:${ss}.${ms}`;
    } catch {
        return ts;
    }
}

function parseExtras(extras?: string | null): Record<string, unknown> | null {
    if (!extras) return null;
    try {
        return JSON.parse(extras);
    } catch {
        return null;
    }
}

function extrasToSearchBlob(extrasRaw?: string | null): string {
    if (!extrasRaw) return "";

    // Fast path: raw JSON string still often contains keys/values in plain text,
    // so include it in search even if parsing fails.
    let blob = extrasRaw;

    const parsed = parseExtras(extrasRaw);
    if (parsed) {
        // Make keys searchable even when values are nested.
        // Also include a stable stringified version for values.
        const keys = Object.keys(parsed).join(" ");
        let values = "";
        try {
            values = JSON.stringify(parsed);
        } catch {
            values = "";
        }
        blob = `${blob} ${keys} ${values}`;
    }

    return blob;
}

function entryToSearchBlob(entry: LogEntry): string {
    return [
        entry.event,
        entry.logger,
        entry.level,
        entry.timestamp,
        extrasToSearchBlob(entry.extras),
    ]
        .filter(Boolean)
        .join("\n")
        .toLowerCase();
}

/** Convert an ISO 8601 string into the format `<input type="datetime-local">`
 *  expects (`YYYY-MM-DDTHH:mm`). The input renders in the browser's local
 *  timezone, so we display the local representation of the UTC instant. */
function isoToLocalInputValue(iso: string | null): string {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
        d.getHours(),
    )}:${pad(d.getMinutes())}`;
}

/** Convert a `datetime-local` input value (interpreted in local time) into a
 *  UTC ISO 8601 string. Returns empty string for empty/invalid input. */
function localInputValueToIso(value: string): string {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return d.toISOString();
}

function LogLine({ entry }: { entry: LogEntry }) {
    const [expanded, setExpanded] = useState(false);
    const extras = parseExtras(entry.extras);
    const hasExtras = extras && Object.keys(extras).length > 0;

    return (
        <div className="group border-b border-border/60">
            <div
                className={cn(
                    "flex items-baseline gap-2 px-3 py-1 text-xs font-mono leading-5",
                    hasExtras && "cursor-pointer hover:bg-muted/40",
                )}
                role={hasExtras ? "button" : undefined}
                tabIndex={hasExtras ? 0 : undefined}
                aria-expanded={hasExtras ? expanded : undefined}
                onClick={hasExtras ? () => setExpanded((v) => !v) : undefined}
                onKeyDown={
                    hasExtras
                        ? (e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  setExpanded((v) => !v);
                              }
                          }
                        : undefined
                }
            >
                {/* timestamp */}
                <span className="w-[88px] shrink-0 text-muted-foreground/70">
                    {formatTimestamp(entry.timestamp)}
                </span>

                {/* level badge */}
                <span
                    className={cn(
                        "w-7 shrink-0 font-semibold",
                        levelColor(entry.level),
                    )}
                >
                    {levelLabel(entry.level)}
                </span>

                {/* logger name */}
                <span className="max-w-[180px] shrink-0 truncate text-muted-foreground">
                    {entry.logger.split(".").pop() ?? entry.logger}
                </span>

                {/* event message */}
                <span className="break-all text-foreground">{entry.event}</span>

                {/* expand indicator */}
                {hasExtras && (
                    <span className="ml-auto shrink-0 text-muted-foreground/70 transition-colors group-hover:text-muted-foreground">
                        {expanded ? "▲" : "▼"}
                    </span>
                )}
            </div>

            {/* extras panel */}
            {expanded && hasExtras && (
                <div
                    className="px-3 pb-2 pt-0.5 font-mono text-xs"
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                >
                    <div className="space-y-0.5 rounded-md border bg-muted/40 px-3 py-2">
                        {Object.entries(extras!).map(([k, v]) => (
                            <div key={k} className="flex gap-2">
                                <span className="shrink-0 text-muted-foreground">
                                    {k}
                                </span>
                                <span className="break-all text-foreground/80">
                                    {typeof v === "object"
                                        ? JSON.stringify(v)
                                        : String(v)}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

export function LogViewer({ generationId, className }: LogViewerProps) {
    const router = useRouter();
    const searchParams = useSearchParams();

    // Initial state from URL params so a refresh restores the same view.
    const initialLevel = searchParams.get("level") ?? "all";
    const initialFromIso = searchParams.get("from");
    const initialToIso = searchParams.get("to");

    const [entries, setEntries] = useState<LogEntryWithSeq[]>([]);
    const [connected, setConnected] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [filter, setFilter] = useState("");
    const [levelFilter, setLevelFilter] = useState<string>(initialLevel);
    // We hold local-input strings in component state (what the inputs render),
    // and ISO strings in a separate ref/state for the actual fetch — that lets
    // us debounce the network call without lagging the inputs.
    const [fromInput, setFromInput] = useState(() =>
        isoToLocalInputValue(initialFromIso),
    );
    const [toInput, setToInput] = useState(() =>
        isoToLocalInputValue(initialToIso),
    );
    const [fromIso, setFromIso] = useState<string | null>(initialFromIso);
    const [toIso, setToIso] = useState<string | null>(initialToIso);
    const [autoScroll, setAutoScroll] = useState(true);
    const containerRef = useRef<HTMLDivElement>(null);
    const esRef = useRef<EventSource | null>(null);
    const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const reconnectAttemptsRef = useRef(0);
    const aliveRef = useRef(true);

    // True while the user has picked at least one bound — in this mode we
    // disable the SSE stream and use the historical snapshot endpoint.
    const timeFilterActive = Boolean(fromIso || toIso);

    // Keep URL query params in sync with the current selection so a refresh
    // restores the view. We use `replace` (not `push`) to avoid filling the
    // browser history with intermediate states.
    useEffect(() => {
        const params = new URLSearchParams(searchParams.toString());
        if (levelFilter && levelFilter !== "all") {
            params.set("level", levelFilter);
        } else {
            params.delete("level");
        }
        if (fromIso) {
            params.set("from", fromIso);
        } else {
            params.delete("from");
        }
        if (toIso) {
            params.set("to", toIso);
        } else {
            params.delete("to");
        }
        const qs = params.toString();
        const url = qs ? `?${qs}` : window.location.pathname;
        router.replace(url, { scroll: false });
        // We deliberately omit `searchParams` and `router` from deps to avoid
        // a feedback loop — they are stable enough in App Router for this
        // synchronization pattern.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [levelFilter, fromIso, toIso]);

    // Debounce conversion of inputs → ISO state (which triggers fetches).
    useEffect(() => {
        const t = setTimeout(() => {
            setFromIso(fromInput ? localInputValueToIso(fromInput) : null);
            setToIso(toInput ? localInputValueToIso(toInput) : null);
        }, 300);
        return () => clearTimeout(t);
    }, [fromInput, toInput]);

    const connect = useCallback(() => {
        if (!aliveRef.current) return;
        if (esRef.current) {
            esRef.current.close();
            esRef.current = null;
        }
        if (timeFilterActive) {
            // Live tailing is suspended while a time range is active.
            setConnected(false);
            return;
        }

        const es = new EventSource(`/api/gateway/logs/${generationId}/stream`);
        esRef.current = es;

        es.onopen = () => {
            if (!aliveRef.current) return;
            reconnectAttemptsRef.current = 0;
            setConnected(true);
            setError(null);
        };

        es.onmessage = (event) => {
            if (!aliveRef.current) return;
            try {
                const data = JSON.parse(event.data);
                if (data.type === "ping" || data.type === "error") {
                    if (data.type === "error") setError(data.message);
                    return;
                }

                const entry = data as LogEntry;
                setEntries((prev) => {
                    const nextSeq = (prev.at(-1)?.__seq ?? -1) + 1;
                    return [...prev, { ...entry, __seq: nextSeq }];
                });
            } catch {
                // ignore parse errors
            }
        };

        es.onerror = () => {
            es.close();
            if (!aliveRef.current) return;
            setConnected(false);
            const attempt = reconnectAttemptsRef.current;
            const delayMs = Math.min(30_000, 1000 * 2 ** attempt);
            reconnectAttemptsRef.current = attempt + 1;
            setError(
                `Connection lost. Reconnecting in ${Math.round(delayMs / 1000)}s…`,
            );
            reconnectTimerRef.current = setTimeout(connect, delayMs);
        };
    }, [generationId, timeFilterActive]);

    // Historical fetch for time-filtered mode.
    useEffect(() => {
        if (!timeFilterActive) return;
        let cancelled = false;
        const params = new URLSearchParams();
        if (fromIso) params.set("from", fromIso);
        if (toIso) params.set("to", toIso);
        const url = `/api/gateway/logs/${generationId}?${params.toString()}`;

        (async () => {
            try {
                const res = await fetch(url);
                if (!res.ok) {
                    if (!cancelled) {
                        setError(`Failed to load logs (${res.status})`);
                    }
                    return;
                }
                const body = (await res.json()) as { entries: LogEntry[] };
                if (cancelled) return;
                const stamped: LogEntryWithSeq[] = body.entries.map((e, i) => ({
                    ...e,
                    __seq: i,
                }));
                setEntries(stamped);
                setError(null);
            } catch (e) {
                if (!cancelled) {
                    setError(
                        e instanceof Error
                            ? e.message
                            : "Failed to load logs",
                    );
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [generationId, timeFilterActive, fromIso, toIso]);

    useEffect(() => {
        aliveRef.current = true;
        // Reset entries when toggling between live and historical modes —
        // mixing the two would produce an inconsistent view.
        if (timeFilterActive) {
            // historical fetcher will repopulate
        } else {
            setEntries([]);
        }
        connect();
        return () => {
            aliveRef.current = false;
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
                reconnectTimerRef.current = null;
            }
            esRef.current?.close();
            esRef.current = null;
        };
    }, [connect, timeFilterActive]);

    const filtered = useMemo(
        () =>
            entries.filter((e) => {
                const matchLevel =
                    levelFilter === "all" ||
                    e.level.toLowerCase() === levelFilter;

                const query = filter.trim().toLowerCase();
                if (!query) return matchLevel;

                // Search across message, logger, level, timestamp, and extras
                // (keys + values).
                return matchLevel && entryToSearchBlob(e).includes(query);
            }),
        [entries, levelFilter, filter],
    );

    // Virtualize the rendered log lines. With 10k+ entries the previous
    // ``filtered.map(...)`` flat list rendered every line into the DOM,
    // which choked the browser on long generations. The virtualizer keeps
    // only ~30 rows mounted at a time.
    const virtualizer = useVirtualizer({
        count: filtered.length,
        getScrollElement: () => containerRef.current,
        estimateSize: () => 28,
        overscan: 12,
    });

    const scrollToBottom = useCallback(() => {
        if (filtered.length === 0) return;
        virtualizer.scrollToIndex(filtered.length - 1, { align: "end" });
    }, [virtualizer, filtered.length]);

    // auto-scroll
    useEffect(() => {
        if (autoScroll) {
            scrollToBottom();
        }
    }, [entries.length, autoScroll, scrollToBottom]);

    // detect manual scroll up → disable auto-scroll
    const handleScroll = () => {
        const el = containerRef.current;
        if (!el) return;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        setAutoScroll(atBottom);
    };

    const levels = ["all", "debug", "info", "warning", "error", "critical"];

    const clearTimeRange = () => {
        setFromInput("");
        setToInput("");
        setFromIso(null);
        setToIso(null);
    };

    return (
        <div
            className={cn(
                "flex h-full flex-col overflow-hidden rounded-lg border bg-card text-card-foreground shadow-sm",
                className,
            )}
        >
            {/* toolbar */}
            <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-3 py-2 shrink-0">
                {/* status dot */}
                <span
                    className={cn(
                        "h-2 w-2 shrink-0 rounded-full",
                        timeFilterActive
                            ? "bg-amber-500"
                            : connected
                              ? "bg-emerald-500"
                              : "bg-muted-foreground/40",
                    )}
                    title={
                        timeFilterActive
                            ? "Live stream paused (time range active)"
                            : connected
                              ? "Connected"
                              : "Disconnected"
                    }
                />

                {/* level filter */}
                <div className="flex gap-1">
                    {levels.map((l) => {
                        const active = levelFilter === l;
                        return (
                            <Button
                                key={l}
                                variant={active ? "secondary" : "ghost"}
                                size="sm"
                                onClick={() => setLevelFilter(l)}
                                className={cn(
                                    "h-7 px-2 font-mono text-[11px]",
                                    !active && "text-muted-foreground",
                                )}
                            >
                                {l === "all" ? "ALL" : levelLabel(l)}
                            </Button>
                        );
                    })}
                </div>

                <Separator orientation="vertical" className="mx-1 h-6" />

                {/* time-range filter */}
                <div className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                    <label htmlFor="logs-from" className="shrink-0">
                        From
                    </label>
                    <Input
                        id="logs-from"
                        type="datetime-local"
                        value={fromInput}
                        onChange={(e) => setFromInput(e.target.value)}
                        className="h-7 w-44 font-mono text-[11px]"
                    />
                    <label htmlFor="logs-to" className="ml-1 shrink-0">
                        To
                    </label>
                    <Input
                        id="logs-to"
                        type="datetime-local"
                        value={toInput}
                        onChange={(e) => setToInput(e.target.value)}
                        className="h-7 w-44 font-mono text-[11px]"
                    />
                    {(fromInput || toInput) && (
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={clearTimeRange}
                            className="h-7 px-2 font-mono text-[11px] text-muted-foreground"
                        >
                            Clear
                        </Button>
                    )}
                </div>

                <Separator orientation="vertical" className="mx-1 h-6" />

                {/* text search */}
                <Input
                    type="text"
                    placeholder="Filter (msg/logger/level/extras)…"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    className="ml-auto h-7 w-56 font-mono text-xs"
                />

                {/* entry count */}
                <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                    {filtered.length}/{entries.length}
                </span>

                <Separator orientation="vertical" className="mx-1 h-6" />

                {/* follow */}
                <div className="flex items-center gap-2 shrink-0">
                    <Switch
                        checked={autoScroll}
                        onCheckedChange={(v) => {
                            setAutoScroll(v);
                            if (v) scrollToBottom();
                        }}
                        aria-label="Follow logs"
                        disabled={timeFilterActive}
                    />
                    <span className="font-mono text-[11px] text-muted-foreground">
                        Follow
                    </span>
                </div>

                {/* clear all */}
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEntries([])}
                    className="h-7 px-2 font-mono text-[11px] text-muted-foreground"
                >
                    Wipe
                </Button>
            </div>

            {/* error banner */}
            {error && (
                <div className="shrink-0 border-b border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-mono text-amber-700 dark:text-amber-300">
                    {error}
                </div>
            )}

            {/* log lines */}
            <div
                ref={containerRef}
                onScroll={handleScroll}
                className="flex-1 overflow-y-auto"
                style={{ contain: "strict" }}
            >
                {filtered.length === 0 ? (
                    <div className="flex h-full items-center justify-center text-xs font-mono text-muted-foreground">
                        {entries.length === 0
                            ? timeFilterActive
                                ? "No logs in the selected range"
                                : "Waiting for logs…"
                            : "No matching entries"}
                    </div>
                ) : (
                    <div
                        style={{
                            height: virtualizer.getTotalSize(),
                            width: "100%",
                            position: "relative",
                        }}
                    >
                        {virtualizer.getVirtualItems().map((row) => {
                            const entry = filtered[row.index];
                            return (
                                <div
                                    key={entry.__seq}
                                    ref={virtualizer.measureElement}
                                    data-index={row.index}
                                    style={{
                                        position: "absolute",
                                        top: 0,
                                        left: 0,
                                        right: 0,
                                        transform: `translateY(${row.start}px)`,
                                    }}
                                >
                                    <LogLine entry={entry} />
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* auto-scroll indicator */}
            {!autoScroll && (
                <div className="shrink-0 border-t bg-muted/30 py-1">
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                            setAutoScroll(true);
                            scrollToBottom();
                        }}
                        className="mx-auto flex h-7 font-mono text-[11px] text-muted-foreground"
                    >
                        ↓ Scroll to bottom
                    </Button>
                </div>
            )}
        </div>
    );
}
