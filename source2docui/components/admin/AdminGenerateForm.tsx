"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PresetPicker } from "@/components/admin/PresetPicker";
import { useRepositories } from "@/hooks/useRepositories";

type GenerationMode = "full" | "incremental";
type OutputLanguage = "en" | "ru";

function splitLines(value: string): string[] {
    // Accept both newline and comma separators so paste-from-git or
    // hand-typed lists both work. Empty entries are filtered.
    return value
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
}

export function AdminGenerateForm() {
    const router = useRouter();
    const { repositories, loading: reposLoading, refetch: refetchRepos } = useRepositories();

    const [mode, setMode] = useState<GenerationMode>("full");
    const [repoId, setRepoId] = useState("");
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [preset, setPreset] = useState<string | null>(null);
    const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>("en");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Incremental-mode fields. ``baseGenerationId`` is optional — the gateway
    // resolves to the latest bundle for the repo when omitted.
    const [baseGenerationId, setBaseGenerationId] = useState("");
    const [changedFilesText, setChangedFilesText] = useState("");
    const [deletedFilesText, setDeletedFilesText] = useState("");
    const [fromCommit, setFromCommit] = useState("");
    const [toCommit, setToCommit] = useState("");

    async function onSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (!repoId) {
            setError("Select a repository first");
            return;
        }

        if (mode === "incremental") {
            const changedFiles = splitLines(changedFilesText);
            const deletedFiles = splitLines(deletedFilesText);
            const hasFiles = changedFiles.length > 0 || deletedFiles.length > 0;
            const hasRange = fromCommit.trim().length > 0 && toCommit.trim().length > 0;
            if (!hasFiles && !hasRange) {
                setError(
                    "Incremental mode requires either a list of changed/deleted files or both from-commit and to-commit",
                );
                return;
            }
        }

        setError(null);
        setSubmitting(true);

        const basePayload: Record<string, unknown> = {
            repo_id: repoId,
            name: name || undefined,
            description: description || undefined,
            preset: preset || undefined,
            // ``generation`` accepts only the fields we explicitly set; the
            // gateway's GenerationConfigRequest fills the rest with defaults.
            generation: { output_language: outputLanguage },
        };

        let endpoint: string;
        let payload: Record<string, unknown>;
        if (mode === "incremental") {
            payload = {
                ...basePayload,
                base_generation_id: baseGenerationId.trim() || undefined,
                changed_files: splitLines(changedFilesText),
                deleted_files: splitLines(deletedFilesText),
                from_commit: fromCommit.trim() || undefined,
                to_commit: toCommit.trim() || undefined,
                head_sha: toCommit.trim() || undefined,
            };
            endpoint = "/api/gateway/tasks/incremental";
        } else {
            payload = basePayload;
            endpoint = "/api/gateway/tasks";
        }

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                throw new Error(body?.detail || `Gateway returned ${response.status}`);
            }
            const result = await response.json();
            toast.success(
                mode === "incremental"
                    ? "Iterative task created"
                    : "Generation task created",
            );
            router.push(`/streams/${result.generation_id}`);
        } catch (err) {
            const message = err instanceof Error ? err.message : "Failed to start generation";
            setError(message);
            toast.error(message);
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <form onSubmit={onSubmit} className="space-y-6">
            <Card>
                <CardHeader>
                    <CardTitle>Generate documentation</CardTitle>
                    <CardDescription>
                        Pick a repository and preset; credentials are pulled from the
                        server-side preset and never leave the gateway.
                    </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="space-y-2">
                        <Label>Mode</Label>
                        <div className="flex gap-2" role="radiogroup">
                            {(
                                [
                                    {
                                        value: "full",
                                        label: "Full",
                                        hint: "Re-run the whole pipeline from scratch.",
                                    },
                                    {
                                        value: "incremental",
                                        label: "Incremental",
                                        hint: "Update an existing bundle: rewrite only pages whose source files changed.",
                                    },
                                ] as const
                            ).map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    role="radio"
                                    aria-checked={mode === option.value}
                                    onClick={() => setMode(option.value)}
                                    className={`flex-1 rounded-lg border px-3 py-2 text-left text-sm transition ${
                                        mode === option.value
                                            ? "border-primary bg-primary/10"
                                            : "border-border hover:bg-muted"
                                    }`}
                                >
                                    <div className="font-medium">{option.label}</div>
                                    <div className="mt-1 text-xs text-muted-foreground">
                                        {option.hint}
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="repo">Repository</Label>
                        <Select
                            value={repoId}
                            onValueChange={(value) => {
                                setRepoId(value);
                                if (!name) {
                                    const repo = repositories.find(
                                        (item) => item.repo_id === value,
                                    );
                                    if (repo) setName(repo.name);
                                }
                            }}
                            disabled={reposLoading}
                        >
                            <SelectTrigger id="repo">
                                <SelectValue
                                    placeholder={
                                        reposLoading
                                            ? "Loading repositories…"
                                            : "Choose a repository"
                                    }
                                />
                            </SelectTrigger>
                            <SelectContent>
                                {repositories.map((repo) => {
                                    const cloning = !repo.s3_key;
                                    return (
                                        <SelectItem
                                            key={repo.repo_id}
                                            value={repo.repo_id}
                                            disabled={cloning}
                                        >
                                            {repo.name}
                                            {cloning ? " — cloning…" : ""}
                                        </SelectItem>
                                    );
                                })}
                            </SelectContent>
                        </Select>
                        {repositories.some((r) => !r.s3_key) && (
                            <button
                                type="button"
                                onClick={() => refetchRepos()}
                                className="text-xs text-muted-foreground underline hover:text-foreground"
                            >
                                Some repositories are still cloning — refresh
                            </button>
                        )}
                    </div>

                    <div className="space-y-2">
                        <Label>Preset</Label>
                        <PresetPicker value={preset} onChange={setPreset} />
                        <p className="text-xs text-muted-foreground">
                            Manage presets in
                            <a className="ml-1 underline" href="/admin/presets">
                                Admin → Presets
                            </a>
                            .
                        </p>
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="name">Documentation name (optional)</Label>
                        <Input
                            id="name"
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                        />
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="description">Description (optional)</Label>
                        <Textarea
                            id="description"
                            rows={2}
                            value={description}
                            onChange={(event) => setDescription(event.target.value)}
                        />
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="output-language">
                            Documentation language
                        </Label>
                        <Select
                            value={outputLanguage}
                            onValueChange={(value) =>
                                setOutputLanguage(value as OutputLanguage)
                            }
                        >
                            <SelectTrigger id="output-language">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="en">English</SelectItem>
                                <SelectItem value="ru">Русский</SelectItem>
                            </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground">
                            All agents (planner, writer, critic, diagrammer)
                            render their output in this language. The critic
                            also flags pages whose body drifts to a different
                            language.
                        </p>
                    </div>
                </CardContent>
            </Card>

            {mode === "incremental" && (
                <Card>
                    <CardHeader>
                        <CardTitle>Iterative update</CardTitle>
                        <CardDescription>
                            Updates an existing bundle by re-running the writer
                            only for pages whose source files changed. Pages
                            whose source files were entirely deleted are
                            carried forward as deprecated. Provide either
                            explicit file lists or a commit range; the worker
                            computes the diff on the cloned repo when both
                            commits are given.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="space-y-2">
                            <Label htmlFor="base-generation-id">
                                Base bundle generation_id (optional)
                            </Label>
                            <Input
                                id="base-generation-id"
                                placeholder="defaults to the latest bundle for the repo"
                                value={baseGenerationId}
                                onChange={(event) =>
                                    setBaseGenerationId(event.target.value)
                                }
                            />
                        </div>

                        <div className="grid gap-4 md:grid-cols-2">
                            <div className="space-y-2">
                                <Label htmlFor="changed-files">
                                    Changed files
                                </Label>
                                <Textarea
                                    id="changed-files"
                                    rows={5}
                                    placeholder={
                                        "src/auth.py\nsrc/api/users.py"
                                    }
                                    value={changedFilesText}
                                    onChange={(event) =>
                                        setChangedFilesText(event.target.value)
                                    }
                                />
                                <p className="text-xs text-muted-foreground">
                                    One path per line, or comma-separated.
                                </p>
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="deleted-files">
                                    Deleted files (optional)
                                </Label>
                                <Textarea
                                    id="deleted-files"
                                    rows={5}
                                    placeholder={"src/legacy.py"}
                                    value={deletedFilesText}
                                    onChange={(event) =>
                                        setDeletedFilesText(event.target.value)
                                    }
                                />
                                <p className="text-xs text-muted-foreground">
                                    Pages backed entirely by these files are
                                    marked deprecated.
                                </p>
                            </div>
                        </div>

                        <div className="rounded-lg border border-border p-3 text-sm">
                            <div className="mb-2 font-medium">
                                Or compute the diff server-side
                            </div>
                            <p className="mb-3 text-xs text-muted-foreground">
                                Fill both commits to have the worker run{" "}
                                <code className="font-mono">
                                    git diff --name-status from..to
                                </code>{" "}
                                itself (requires a git-cloned repo).
                            </p>
                            <div className="grid gap-3 md:grid-cols-2">
                                <div className="space-y-1">
                                    <Label htmlFor="from-commit" className="text-xs">
                                        from_commit (base SHA)
                                    </Label>
                                    <Input
                                        id="from-commit"
                                        placeholder="abc1234"
                                        value={fromCommit}
                                        onChange={(event) =>
                                            setFromCommit(event.target.value)
                                        }
                                    />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="to-commit" className="text-xs">
                                        to_commit (head SHA)
                                    </Label>
                                    <Input
                                        id="to-commit"
                                        placeholder="def5678"
                                        value={toCommit}
                                        onChange={(event) =>
                                            setToCommit(event.target.value)
                                        }
                                    />
                                </div>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            )}

            {error && (
                <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}

            <div className="flex justify-end">
                <Button type="submit" disabled={submitting}>
                    {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    {submitting
                        ? "Starting…"
                        : mode === "incremental"
                          ? "Start iterative update"
                          : "Start generation"}
                </Button>
            </div>
        </form>
    );
}
