"use client";

import * as React from "react";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetHeader,
    SheetTitle,
} from "../ui/sheet";
import { Input } from "../ui/input";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Spinner } from "../ui/spinner";
import { cn } from "../../lib/utils";
import {
    searchProject,
    SearchError,
    type SearchMode,
    type SearchRequest,
    type SearchResponse,
    type SearchResult,
} from "../../lib/api/search";
import {
    Copy,
    Check,
    Filter,
    FileText,
    Search as SearchIcon,
    X,
} from "lucide-react";
import { toast } from "sonner";

interface WikiSearchPanelProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    repositoryId?: string;
    /**
     * External submission trigger from the wiki header search bar.
     * `token` should change on every submit (even with the same query string)
     * so the panel re-runs the search.
     */
    submission?: { query: string; token: number } | null;
}

const MODE_LABEL: Record<SearchMode, string> = {
    semantic: "Semantic",
    fulltext: "Fulltext",
};

function escapeRegExp(input: string): string {
    return input.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function buildHighlightTokens(query: string): string[] {
    return query
        .split(/\s+/)
        .map((t) => t.trim())
        .filter((t) => t.length >= 2);
}

function HighlightedSnippet({
    text,
    tokens,
    maxLines = 5,
}: {
    text: string;
    tokens: string[];
    maxLines?: number;
}) {
    const lines = React.useMemo(() => {
        const split = String(text || "").split("\n");
        if (split.length <= maxLines) return split;
        return split.slice(0, maxLines);
    }, [text, maxLines]);

    const truncated =
        String(text || "").split("\n").length > maxLines;

    const pattern = React.useMemo(() => {
        if (tokens.length === 0) return null;
        const escaped = tokens.map(escapeRegExp).join("|");
        return new RegExp(`(${escaped})`, "gi");
    }, [tokens]);

    return (
        <pre className="m-0 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90">
            {lines.map((line, idx) => (
                <div key={idx}>
                    {pattern
                        ? line.split(pattern).map((part, i) =>
                              pattern.test(part) ? (
                                  <mark
                                      key={i}
                                      className="rounded-sm bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-500/40"
                                  >
                                      {part}
                                  </mark>
                              ) : (
                                  <React.Fragment key={i}>{part}</React.Fragment>
                              ),
                          )
                        : line}
                </div>
            ))}
            {truncated && (
                <div className="text-muted-foreground">…</div>
            )}
        </pre>
    );
}

function ResultRow({
    result,
    tokens,
}: {
    result: SearchResult;
    tokens: string[];
}) {
    const [copied, setCopied] = React.useState(false);

    const location = `${result.source.file_path}:${result.source.start_line}-${result.source.end_line}`;

    async function copyLocation() {
        try {
            await navigator.clipboard.writeText(location);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            toast.error("Could not copy to clipboard");
        }
    }

    return (
        <article className="rounded-md border border-border bg-card p-3 text-sm shadow-xs">
            <header className="mb-2 flex flex-wrap items-center gap-2">
                <FileText className="size-3.5 text-muted-foreground" />
                <code className="break-all font-mono text-xs text-foreground">
                    {location}
                </code>
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Copy file path"
                    onClick={copyLocation}
                >
                    {copied ? (
                        <Check className="size-3.5" />
                    ) : (
                        <Copy className="size-3.5" />
                    )}
                </Button>
                <div className="ml-auto flex items-center gap-1.5">
                    {result.source.language && (
                        <Badge variant="secondary" className="text-[10px]">
                            {result.source.language}
                        </Badge>
                    )}
                    <Badge variant="outline" className="text-[10px]">
                        {result.score.toFixed(3)}
                    </Badge>
                </div>
            </header>
            <div className="rounded bg-muted/50 px-2 py-1.5">
                <HighlightedSnippet text={result.text} tokens={tokens} />
            </div>
        </article>
    );
}

export function WikiSearchPanel({
    open,
    onOpenChange,
    repositoryId,
    submission,
}: WikiSearchPanelProps) {
    const [query, setQuery] = React.useState(submission?.query ?? "");
    const [submittedQuery, setSubmittedQuery] = React.useState("");
    const [mode, setMode] = React.useState<SearchMode>("semantic");
    const [showFilters, setShowFilters] = React.useState(false);
    const [filePath, setFilePath] = React.useState("");
    const [directory, setDirectory] = React.useState("");
    const [language, setLanguage] = React.useState("");
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const [response, setResponse] = React.useState<SearchResponse | null>(null);

    const inputRef = React.useRef<HTMLInputElement>(null);
    const abortRef = React.useRef<AbortController | null>(null);

    React.useEffect(() => {
        if (open) {
            // focus the input when the panel opens
            const id = window.setTimeout(() => {
                inputRef.current?.focus();
                inputRef.current?.select();
            }, 50);
            return () => window.clearTimeout(id);
        }
        // abort any in-flight request when the panel closes
        return () => {
            abortRef.current?.abort();
            abortRef.current = null;
        };
    }, [open]);

    const tokens = React.useMemo(
        () => buildHighlightTokens(submittedQuery),
        [submittedQuery],
    );

    const runSearch = React.useCallback(
        async (queryOverride?: string) => {
            const trimmed = (queryOverride ?? query).trim();
            if (!trimmed) return;
            if (!repositoryId) {
                const msg =
                    "No repository scope available for this wiki page.";
                setError(msg);
                toast.error(msg);
                return;
            }

            abortRef.current?.abort();
            const controller = new AbortController();
            abortRef.current = controller;

            const filters: SearchRequest["filters"] = {};
            if (filePath.trim()) filters.file_path = filePath.trim();
            if (directory.trim()) filters.directory = directory.trim();
            if (language.trim()) filters.language = language.trim();

            const body: SearchRequest = {
                query: trimmed,
                mode,
                limit: 20,
            };
            if (Object.keys(filters).length > 0) body.filters = filters;

            setLoading(true);
            setError(null);
            setSubmittedQuery(trimmed);

            try {
                const res = await searchProject(repositoryId, body, {
                    signal: controller.signal,
                });
                setResponse(res);
            } catch (err) {
                if ((err as { name?: string })?.name === "AbortError") return;
                const message =
                    err instanceof SearchError
                        ? err.message
                        : err instanceof Error
                          ? err.message
                          : "Search request failed";
                setError(message);
                setResponse(null);
                toast.error(message);
            } finally {
                if (abortRef.current === controller) {
                    abortRef.current = null;
                }
                setLoading(false);
            }
        },
        [query, repositoryId, mode, filePath, directory, language],
    );

    // Auto-run a search when the parent bar submits via the submission token.
    const lastSubmittedToken = React.useRef<number | null>(null);
    React.useEffect(() => {
        if (!submission) return;
        if (lastSubmittedToken.current === submission.token) return;
        lastSubmittedToken.current = submission.token;
        setQuery(submission.query);
        void runSearch(submission.query);
    }, [submission, runSearch]);

    function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
        if (e.key === "Enter") {
            e.preventDefault();
            void runSearch();
        }
    }

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                className="w-full overflow-y-auto p-0 sm:max-w-xl"
            >
                <SheetHeader className="border-b border-border bg-background/80 backdrop-blur-md">
                    <SheetTitle className="flex items-center gap-2">
                        <SearchIcon className="size-4" />
                        Search project
                    </SheetTitle>
                    <SheetDescription>
                        Search code across this project&apos;s indexed sources.
                    </SheetDescription>

                    <div className="mt-2 flex items-center gap-2">
                        <Input
                            ref={inputRef}
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder="Search code, e.g. parseConfig, JWT validation"
                            className="flex-1"
                            disabled={!repositoryId}
                        />
                        <Button
                            type="button"
                            onClick={() => void runSearch()}
                            disabled={
                                loading || !query.trim() || !repositoryId
                            }
                        >
                            {loading ? (
                                <Spinner className="size-4" />
                            ) : (
                                <SearchIcon className="size-4" />
                            )}
                            <span className="hidden sm:inline">Search</span>
                        </Button>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        <div
                            role="tablist"
                            aria-label="Search mode"
                            className="inline-flex rounded-md border border-border bg-muted p-0.5"
                        >
                            {(Object.keys(MODE_LABEL) as SearchMode[]).map(
                                (m) => (
                                    <button
                                        key={m}
                                        type="button"
                                        role="tab"
                                        aria-selected={mode === m}
                                        onClick={() => setMode(m)}
                                        className={cn(
                                            "rounded px-3 py-1 text-xs font-medium transition-colors",
                                            mode === m
                                                ? "bg-background text-foreground shadow-xs"
                                                : "text-muted-foreground hover:text-foreground",
                                        )}
                                    >
                                        {MODE_LABEL[m]}
                                    </button>
                                ),
                            )}
                        </div>
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => setShowFilters((s) => !s)}
                            aria-expanded={showFilters}
                        >
                            <Filter className="size-3.5" />
                            <span>
                                {showFilters ? "Hide filters" : "Filters"}
                            </span>
                        </Button>
                        {!repositoryId && (
                            <span className="text-xs text-destructive">
                                No repository in scope
                            </span>
                        )}
                    </div>

                    {showFilters && (
                        <div className="mt-2 grid gap-2 rounded-md border border-border bg-muted/30 p-3 sm:grid-cols-3">
                            <label className="space-y-1 text-xs text-muted-foreground">
                                <span>file_path</span>
                                <Input
                                    value={filePath}
                                    onChange={(e) =>
                                        setFilePath(e.target.value)
                                    }
                                    placeholder="src/auth/login.ts"
                                    className="h-8"
                                />
                            </label>
                            <label className="space-y-1 text-xs text-muted-foreground">
                                <span>directory</span>
                                <Input
                                    value={directory}
                                    onChange={(e) =>
                                        setDirectory(e.target.value)
                                    }
                                    placeholder="src/auth"
                                    className="h-8"
                                />
                            </label>
                            <label className="space-y-1 text-xs text-muted-foreground">
                                <span>language</span>
                                <Input
                                    value={language}
                                    onChange={(e) =>
                                        setLanguage(e.target.value)
                                    }
                                    placeholder="python"
                                    className="h-8"
                                />
                            </label>
                            {(filePath || directory || language) && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => {
                                        setFilePath("");
                                        setDirectory("");
                                        setLanguage("");
                                    }}
                                    className="justify-self-start sm:col-span-3"
                                >
                                    <X className="size-3.5" />
                                    Clear filters
                                </Button>
                            )}
                        </div>
                    )}
                </SheetHeader>

                <div className="flex flex-col gap-3 px-4 py-4">
                    {submittedQuery && !loading && response && (
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span>
                                Showing{" "}
                                <strong className="text-foreground">
                                    {response.results.length}
                                </strong>{" "}
                                of{" "}
                                <strong className="text-foreground">
                                    {response.total}
                                </strong>{" "}
                                for{" "}
                                <em className="text-foreground">
                                    “{submittedQuery}”
                                </em>
                            </span>
                            <Badge variant="outline" className="text-[10px]">
                                {MODE_LABEL[response.mode]}
                            </Badge>
                        </div>
                    )}

                    {loading && (
                        <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
                            <Spinner />
                            <span>Searching…</span>
                        </div>
                    )}

                    {error && !loading && (
                        <div
                            role="alert"
                            className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
                        >
                            {error}
                        </div>
                    )}

                    {!loading &&
                        !error &&
                        response &&
                        response.results.length === 0 && (
                            <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-muted-foreground">
                                <SearchIcon className="size-8" />
                                <p className="text-sm">
                                    No matches for{" "}
                                    <em className="text-foreground">
                                        “{submittedQuery}”
                                    </em>
                                </p>
                                <p className="text-xs">
                                    Try a different query or switch search
                                    mode.
                                </p>
                            </div>
                        )}

                    {!loading && !response && !error && (
                        <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-muted-foreground">
                            <SearchIcon className="size-8" />
                            <p className="text-sm">
                                Enter a query to search this project.
                            </p>
                            <p className="text-xs">
                                Press{" "}
                                <kbd className="rounded border border-border bg-muted px-1 text-[10px]">
                                    Enter
                                </kbd>{" "}
                                to submit.
                            </p>
                        </div>
                    )}

                    {!loading && response && response.results.length > 0 && (
                        <div className="flex flex-col gap-2">
                            {response.results.map((r) => (
                                <ResultRow
                                    key={r.metadata.chunk_id}
                                    result={r}
                                    tokens={tokens}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    );
}
