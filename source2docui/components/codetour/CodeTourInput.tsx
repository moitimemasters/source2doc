"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, Loader2, Sparkles, X } from "lucide-react";

import { codetourAPI, type TourMode } from "@/lib/codetour-api";
import { useRuntimeInfo } from "@/lib/runtime";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";

interface CodeTourInputProps {
    generationId?: string;
}

const QUESTION_TEMPLATES: { label: string; preset: string }[] = [
    {
        label: "Onboarding",
        preset:
            "Help me understand how the project is organized and where the main entry points live.",
    },
    {
        label: "Feature walk-through",
        preset:
            "Walk me through how feature X is implemented (replace X with the area you care about).",
    },
    {
        label: "Architecture deep-dive",
        preset:
            "What's the overall architecture and which key design patterns are in use?",
    },
];

export function CodeTourInput({ generationId }: CodeTourInputProps) {
    const router = useRouter();
    const [query, setQuery] = useState("");
    const [maxSteps, setMaxSteps] = useState(6);
    const [mode, setMode] = useState<TourMode>("overview");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [open, setOpen] = useState(false);

    const { info, loading: runtimeLoading } = useRuntimeInfo();
    const configured = info?.configured ?? false;

    if (!generationId) {
        return null;
    }

    async function handleSubmit(event: React.FormEvent) {
        event.preventDefault();
        if (!query.trim()) {
            setError("Please enter a query");
            return;
        }
        if (!generationId) return;

        setLoading(true);
        setError(null);
        try {
            const response = await codetourAPI.createCodetour({
                query,
                generation_id: generationId,
                max_steps: maxSteps,
                mode,
            });
            router.push(`/tour/${response.tour_id}`);
        } catch (err) {
            setError(
                err instanceof Error
                    ? err.message
                    : "Failed to generate tour. Please try again.",
            );
        } finally {
            setLoading(false);
        }
    }

    if (!open) {
        return (
            <Button
                type="button"
                onClick={() => setOpen(true)}
                className="fixed bottom-6 right-6 z-[70] h-12 px-4 shadow-lg"
                aria-label="Open code tour generator"
                aria-expanded={false}
            >
                <Sparkles className="h-4 w-4 mr-2" />
                Code Tour
            </Button>
        );
    }

    return (
        <Card className="fixed bottom-6 left-1/2 -translate-x-1/2 w-[calc(100%-2rem)] max-w-2xl p-4 shadow-lg border-2 z-[70] max-h-[calc(100vh-5rem)] overflow-y-auto">
            <form onSubmit={handleSubmit} className="space-y-3">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Sparkles className="h-5 w-5 text-primary" />
                        <h3 className="font-semibold">Generate Code Tour</h3>
                    </div>
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => setOpen(false)}
                        aria-label="Close code tour generator"
                    >
                        <X className="h-4 w-4" />
                    </Button>
                </div>

                {!runtimeLoading && !configured && (
                    <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                        Service is not configured yet. Ask an administrator to
                        create a default preset.
                    </div>
                )}

                <div className="space-y-2">
                    <Label htmlFor="query">What do you want to learn?</Label>
                    <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs text-muted-foreground">
                            Templates:
                        </span>
                        {QUESTION_TEMPLATES.map((tpl) => (
                            <Button
                                key={tpl.label}
                                type="button"
                                variant="outline"
                                size="sm"
                                disabled={loading || !configured}
                                onClick={() => setQuery(tpl.preset)}
                            >
                                {tpl.label}
                            </Button>
                        ))}
                    </div>
                    <Input
                        id="query"
                        type="text"
                        placeholder="e.g., How does request authentication flow through the gateway?"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        disabled={loading || !configured}
                        className="w-full"
                    />
                </div>

                <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                        <Label htmlFor="mode">Tour mode</Label>
                        <Select
                            value={mode}
                            onValueChange={(v) => setMode(v as TourMode)}
                            disabled={loading || !configured}
                        >
                            <SelectTrigger id="mode">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="overview">Overview</SelectItem>
                                <SelectItem value="deep-dive">Deep dive</SelectItem>
                                <SelectItem value="gotchas">Gotchas</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="maxSteps">Max steps</Label>
                        <Input
                            id="maxSteps"
                            type="number"
                            min={1}
                            max={20}
                            value={maxSteps}
                            onChange={(e) =>
                                setMaxSteps(parseInt(e.target.value) || 6)
                            }
                            disabled={loading || !configured}
                        />
                    </div>
                </div>

                <Button
                    type="submit"
                    disabled={loading || !query.trim() || !configured}
                    className="w-full"
                >
                    {loading ? (
                        <>
                            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                            Generating...
                        </>
                    ) : (
                        "Generate Tour"
                    )}
                </Button>

                {info?.default_preset && (
                    <p className="text-xs text-muted-foreground">
                        Using preset
                        <code className="ml-1">{info.default_preset.name}</code>
                    </p>
                )}

                {error && (
                    <div className="flex items-center gap-2 text-sm text-destructive">
                        <AlertCircle className="h-4 w-4" />
                        <span>{error}</span>
                    </div>
                )}
            </form>
        </Card>
    );
}
