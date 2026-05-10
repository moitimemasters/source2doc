"use client";

import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
    AlertCircle,
    Loader2,
    Search as SearchIcon,
    Settings2,
} from "lucide-react";

interface BundleInfo {
    generation_id: string;
    name: string | null;
    project_name: string;
    repository?: { name: string | null } | null;
}

interface BundleListResponse {
    bundles: BundleInfo[];
    total: number;
}

interface EmbeddingsCreds {
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
    dimensions: number;
}

interface SearchHit {
    chunk_id: string;
    file_path: string;
    start_line: number;
    end_line: number;
    content: string;
    language?: string | null;
    score: number;
}

interface SearchResponse {
    generation_id: string;
    query: string;
    results: SearchHit[];
}

const EMB_STORAGE_KEY = "source2doc.lastEmbeddingsConfig";

function readStoredEmbeddings(): EmbeddingsCreds | null {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(EMB_STORAGE_KEY);
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch {
        return null;
    }
}

function writeStoredEmbeddings(cfg: EmbeddingsCreds) {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(EMB_STORAGE_KEY, JSON.stringify(cfg));
}

function bundleLabel(b: BundleInfo): string {
    return (
        b.name ||
        b.repository?.name ||
        b.project_name ||
        b.generation_id.slice(0, 8)
    );
}

export function SearchView() {
    const [bundles, setBundles] = useState<BundleInfo[]>([]);
    const [generationId, setGenerationId] = useState<string>("");
    const [query, setQuery] = useState("");
    const [limit, setLimit] = useState(10);
    const [filePath, setFilePath] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [results, setResults] = useState<SearchHit[]>([]);
    const [emb, setEmb] = useState<EmbeddingsCreds | null>(null);
    const [showCreds, setShowCreds] = useState(false);
    const [embForm, setEmbForm] = useState<EmbeddingsCreds>({
        provider: "openai-compatible",
        model: "Qodo-Embed-1-7B",
        api_key: "",
        base_url: "",
        dimensions: 3584,
    });

    useEffect(() => {
        (async () => {
            try {
                const res = await fetch("/api/gateway/docs/bundles");
                const data: BundleListResponse = await res.json();
                setBundles(data.bundles ?? []);
                if (data.bundles?.[0]) {
                    setGenerationId(data.bundles[0].generation_id);
                }
            } catch (err) {
                console.error("Failed to load bundles:", err);
            }
        })();

        const stored = readStoredEmbeddings();
        if (stored) {
            setEmb(stored);
            setEmbForm(stored);
        } else {
            setShowCreds(true);
        }
    }, []);

    function saveCreds() {
        if (!embForm.api_key.trim() || !embForm.base_url.trim()) {
            setError("Embeddings api_key and base_url are required");
            return;
        }
        writeStoredEmbeddings(embForm);
        setEmb(embForm);
        setShowCreds(false);
        setError(null);
    }

    async function handleSearch(e: React.FormEvent) {
        e.preventDefault();
        if (!generationId) {
            setError("Pick a bundle to search in");
            return;
        }
        if (!query.trim()) {
            setError("Enter a search query");
            return;
        }
        if (!emb) {
            setError("Configure embeddings credentials first");
            setShowCreds(true);
            return;
        }
        setError(null);
        setLoading(true);
        setResults([]);
        try {
            const body = {
                generation_id: generationId,
                query,
                limit,
                file_path: filePath.trim() || undefined,
                embeddings: emb,
            };
            const res = await fetch("/api/gateway/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || err.error || "Search failed");
            }
            const data: SearchResponse = await res.json();
            setResults(data.results);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Search failed");
        } finally {
            setLoading(false);
        }
    }

    const queryHint = useMemo(() => {
        if (!query.trim()) return null;
        const reTokens = query
            .split(/\s+/)
            .filter((t) => t.length > 2)
            .slice(0, 8);
        return reTokens.map((t) => t.toLowerCase());
    }, [query]);

    return (
        <div className="container mx-auto px-4 py-6 max-w-5xl">
            <div className="mb-6 flex items-center gap-2">
                <SearchIcon className="h-6 w-6 text-primary" />
                <h1 className="text-2xl font-bold">Semantic search</h1>
            </div>

            <Card className="p-4 space-y-3 mb-6">
                <form onSubmit={handleSearch} className="space-y-3">
                    <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2">
                        <div className="space-y-1">
                            <Label htmlFor="bundle">Bundle</Label>
                            <select
                                id="bundle"
                                value={generationId}
                                onChange={(e) =>
                                    setGenerationId(e.target.value)
                                }
                                className="flex h-10 w-full rounded-md border bg-background px-3 text-sm"
                            >
                                {bundles.length === 0 ? (
                                    <option value="">
                                        No bundles available
                                    </option>
                                ) : (
                                    bundles.map((b) => (
                                        <option
                                            key={b.generation_id}
                                            value={b.generation_id}
                                        >
                                            {bundleLabel(b)} (
                                            {b.generation_id.slice(0, 8)})
                                        </option>
                                    ))
                                )}
                            </select>
                        </div>
                        <div className="flex items-end">
                            <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => setShowCreds((v) => !v)}
                            >
                                <Settings2 className="h-4 w-4 mr-1" />
                                {emb ? "Embeddings" : "Configure embeddings"}
                            </Button>
                        </div>
                    </div>

                    {showCreds && (
                        <div className="rounded-md border bg-muted/30 p-3 space-y-2">
                            <div className="grid grid-cols-2 gap-2">
                                <div className="space-y-1">
                                    <Label className="text-xs">Base URL</Label>
                                    <Input
                                        placeholder="https://.../qodo-embed.../v1"
                                        value={embForm.base_url}
                                        onChange={(e) =>
                                            setEmbForm({
                                                ...embForm,
                                                base_url: e.target.value,
                                            })
                                        }
                                    />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-xs">Model</Label>
                                    <Input
                                        value={embForm.model}
                                        onChange={(e) =>
                                            setEmbForm({
                                                ...embForm,
                                                model: e.target.value,
                                            })
                                        }
                                    />
                                </div>
                            </div>
                            <div className="grid grid-cols-3 gap-2">
                                <div className="col-span-2 space-y-1">
                                    <Label className="text-xs">API Key</Label>
                                    <Input
                                        type="password"
                                        value={embForm.api_key}
                                        onChange={(e) =>
                                            setEmbForm({
                                                ...embForm,
                                                api_key: e.target.value,
                                            })
                                        }
                                    />
                                </div>
                                <div className="space-y-1">
                                    <Label className="text-xs">
                                        Dimensions
                                    </Label>
                                    <Input
                                        type="number"
                                        value={embForm.dimensions}
                                        onChange={(e) =>
                                            setEmbForm({
                                                ...embForm,
                                                dimensions:
                                                    parseInt(e.target.value) ||
                                                    embForm.dimensions,
                                            })
                                        }
                                    />
                                </div>
                            </div>
                            <Button
                                type="button"
                                size="sm"
                                onClick={saveCreds}
                                className="w-full"
                            >
                                Save credentials
                            </Button>
                        </div>
                    )}

                    <div className="space-y-1">
                        <Label htmlFor="q">Query</Label>
                        <div className="flex gap-2">
                            <Input
                                id="q"
                                placeholder="e.g. how does authentication work"
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                                disabled={loading}
                            />
                            <Button
                                type="submit"
                                disabled={loading || !query.trim()}
                            >
                                {loading ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    "Search"
                                )}
                            </Button>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                            <Label htmlFor="filePath">
                                Restrict to file (optional)
                            </Label>
                            <Input
                                id="filePath"
                                placeholder="src/auth.py"
                                value={filePath}
                                onChange={(e) => setFilePath(e.target.value)}
                                disabled={loading}
                            />
                        </div>
                        <div className="space-y-1">
                            <Label htmlFor="limit">Limit</Label>
                            <Input
                                id="limit"
                                type="number"
                                min={1}
                                max={50}
                                value={limit}
                                onChange={(e) =>
                                    setLimit(parseInt(e.target.value) || 10)
                                }
                                disabled={loading}
                            />
                        </div>
                    </div>

                    {error && (
                        <div className="flex items-center gap-2 text-sm text-destructive">
                            <AlertCircle className="h-4 w-4" />
                            <span>{error}</span>
                        </div>
                    )}
                </form>
            </Card>

            <div className="space-y-3">
                {results.length === 0 && !loading && (
                    <p className="text-sm text-muted-foreground text-center py-8">
                        {query.trim()
                            ? "No results yet — submit the form to search."
                            : "Enter a query to start searching."}
                    </p>
                )}
                {results.map((hit) => (
                    <Card key={hit.chunk_id} className="p-3">
                        <div className="flex items-center justify-between mb-2">
                            <code className="text-sm font-mono text-foreground/90">
                                {hit.file_path}:{hit.start_line}–{hit.end_line}
                            </code>
                            <span className="text-xs text-muted-foreground">
                                score {hit.score.toFixed(3)}
                            </span>
                        </div>
                        <pre className="overflow-x-auto bg-muted/30 rounded p-2 text-xs leading-5">
                            {highlight(hit.content, queryHint)}
                        </pre>
                    </Card>
                ))}
            </div>
        </div>
    );
}

function highlight(content: string, tokens: string[] | null): React.ReactNode {
    if (!tokens || tokens.length === 0) return content;
    // Naive token highlight — wraps each match in <mark>.
    const escaped = tokens.map((t) =>
        t.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&"),
    );
    const re = new RegExp(`(${escaped.join("|")})`, "gi");
    const parts = content.split(re);
    return parts.map((part, i) =>
        re.test(part) ? (
            <mark
                key={i}
                className="bg-amber-300/40 dark:bg-amber-300/30 px-0.5 rounded-sm"
            >
                {part}
            </mark>
        ) : (
            <span key={i}>{part}</span>
        ),
    );
}
