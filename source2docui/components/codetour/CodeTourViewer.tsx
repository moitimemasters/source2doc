"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CodetourDetail } from "@/lib/codetour-api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
    AlertTriangle,
    Anchor,
    ArrowRight,
    ChevronLeft,
    ChevronRight,
    Download,
    Flame,
    MessageSquarePlus,
} from "lucide-react";
import { FollowupDialog } from "@/components/codetour/FollowupDialog";

interface CodeTourViewerProps {
    tour: CodetourDetail;
    codeBlocks: React.ReactNode[];
}

const KIND_ICON: Record<string, any> = {
    entry: Anchor,
    transition: ArrowRight,
    leaf: Flame,
    gotcha: AlertTriangle,
};

const KIND_DOT_CLS: Record<string, string> = {
    entry: "bg-blue-500",
    transition: "bg-muted-foreground/40",
    leaf: "bg-emerald-500",
    gotcha: "bg-amber-500",
};

const EXPORT_LANG_MAP: Record<string, string> = {
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    py: "python",
    go: "go",
    rs: "rust",
    java: "java",
    cpp: "cpp",
    c: "c",
    cs: "csharp",
    rb: "ruby",
    php: "php",
    swift: "swift",
    kt: "kotlin",
    yaml: "yaml",
    yml: "yaml",
    json: "json",
    xml: "xml",
    html: "html",
    css: "css",
    scss: "scss",
    sql: "sql",
    sh: "bash",
    bash: "bash",
    md: "markdown",
};

function exportLang(file: string): string {
    const ext = file.split(".").pop()?.toLowerCase() ?? "";
    return EXPORT_LANG_MAP[ext] ?? "";
}

function serializeTourToMarkdown(tour: CodetourDetail): string {
    const lines: string[] = [];
    const title = tour.title?.trim() || "Code Tour";
    lines.push(`# ${title}`);
    lines.push("");

    const query = tour.metadata?.query as string | undefined;
    if (query) {
        lines.push(`> ${query}`);
        lines.push("");
    }

    if (tour.description) {
        lines.push(tour.description);
        lines.push("");
    }

    lines.push(`Generated: ${tour.created_at}`);
    lines.push("");

    tour.steps.forEach((step, idx) => {
        lines.push(`## Step ${idx + 1}: ${step.title}`);
        lines.push("");
        if (step.description) {
            lines.push(step.description);
            lines.push("");
        }
        if (step.key_idea) {
            lines.push(`> **Key idea:** ${step.key_idea}`);
            lines.push("");
        }

        const code = step.code || step.pattern;
        if (code) {
            const lang = exportLang(step.file);
            const range = step.end_line
                ? `${step.line}-${step.end_line}`
                : `${step.line}`;
            lines.push("```" + lang);
            lines.push(`// ${step.file}:${range}`);
            lines.push(code);
            lines.push("```");
            lines.push("");
        } else {
            lines.push(`_File:_ \`${step.file}\``);
            lines.push("");
        }

        if (step.highlights && step.highlights.length > 0) {
            lines.push("**Highlights:**");
            lines.push("");
            for (const h of step.highlights) {
                lines.push(`- L${h.line}: ${h.note}`);
            }
            lines.push("");
        }

        if (idx < tour.steps.length - 1) {
            lines.push("---");
            lines.push("");
        }
    });

    return lines.join("\n");
}

function downloadMarkdown(tour: CodetourDetail): void {
    const md = serializeTourToMarkdown(tour);
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `tour-${tour.tour_id.slice(0, 8)}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

export function CodeTourViewer({ tour, codeBlocks }: CodeTourViewerProps) {
    const router = useRouter();
    const [currentStep, setCurrentStep] = useState(0);
    const [followupOpen, setFollowupOpen] = useState(false);

    const mode = (tour.metadata?.mode as string | undefined) ?? "overview";
    const steps = tour.steps;
    const hasSteps = steps.length > 0;
    const step = hasSteps ? steps[currentStep] : undefined;
    const isFirstStep = currentStep === 0;
    const isLastStep = !hasSteps || currentStep === steps.length - 1;

    if (!hasSteps) {
        return (
            <div className="min-h-screen bg-background">
                <div className="container mx-auto px-4 py-16 max-w-2xl">
                    <Card className="p-8 text-center space-y-4">
                        <AlertTriangle className="h-10 w-10 mx-auto text-amber-500" />
                        <div>
                            <h1 className="text-2xl font-bold mb-2">
                                {tour.title || "Tour has no steps"}
                            </h1>
                            <p className="text-muted-foreground">
                                The agent finished without producing any tour
                                steps. Try a different query or regenerate the
                                tour.
                            </p>
                        </div>
                        <div className="flex justify-center gap-2">
                            <Button
                                variant="outline"
                                onClick={() => router.push("/tour")}
                            >
                                <ChevronLeft className="h-4 w-4 mr-1" />
                                Back to tours
                            </Button>
                            <Button
                                onClick={() => router.push("/")}
                            >
                                Regenerate
                            </Button>
                        </div>
                    </Card>
                </div>
            </div>
        );
    }

    const incomingByStep = useMemo(() => {
        const map = new Map<number, number[]>();
        steps.forEach((s, idx) => {
            for (const target of s.connects_to || []) {
                const list = map.get(target) || [];
                list.push(idx);
                map.set(target, list);
            }
        });
        return map;
    }, [steps]);

    return (
        <div className="min-h-screen bg-background">
            <div className="border-b bg-card">
                <div className="container mx-auto px-4 py-4">
                    <div className="flex items-center justify-between gap-4">
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                                <Badge
                                    variant="outline"
                                    className="text-xs uppercase tracking-wider"
                                >
                                    {mode}
                                </Badge>
                                {tour.status && tour.status !== "completed" && (
                                    <Badge variant="outline">
                                        {tour.status}
                                    </Badge>
                                )}
                            </div>
                            <h1 className="text-2xl font-bold truncate">
                                {tour.title}
                            </h1>
                            <p className="text-muted-foreground line-clamp-2">
                                {tour.description}
                            </p>
                        </div>
                        <div className="flex items-center gap-2">
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => downloadMarkdown(tour)}
                                title="Export tour as Markdown"
                            >
                                <Download className="h-4 w-4 mr-1" />
                                Export Markdown
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => setFollowupOpen(true)}
                            >
                                <MessageSquarePlus className="h-4 w-4 mr-1" />
                                Ask follow-up
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => router.push("/")}
                            >
                                <ChevronLeft className="h-4 w-4 mr-1" />
                                Back
                            </Button>
                        </div>
                    </div>

                    <div className="flex gap-4 mt-3 text-sm text-muted-foreground">
                        <div>
                            Step {currentStep + 1} of {steps.length}
                        </div>
                        <div>
                            Created:{" "}
                            {new Date(tour.created_at).toLocaleDateString()}
                        </div>
                    </div>
                </div>
            </div>

            <div className="container mx-auto px-4 py-8">
                <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-6">
                    <Card className="p-3 lg:sticky lg:top-4 self-start max-h-[calc(100vh-2rem)] overflow-y-auto">
                        <h3 className="font-semibold text-sm px-2 py-2 text-muted-foreground uppercase tracking-wider">
                            Steps
                        </h3>
                        <div className="space-y-0.5">
                            {steps.map((s, idx) => {
                                const kind = (s.kind as string) || "transition";
                                const incoming = incomingByStep.get(idx) || [];
                                const KindIcon =
                                    KIND_ICON[kind] || KIND_ICON.transition;
                                return (
                                    <button
                                        key={idx}
                                        onClick={() => setCurrentStep(idx)}
                                        className={`w-full text-left px-2 py-1.5 rounded text-sm transition-colors flex items-start gap-2 ${
                                            idx === currentStep
                                                ? "bg-primary/10 border-l-2 border-primary"
                                                : "hover:bg-muted border-l-2 border-transparent"
                                        }`}
                                    >
                                        <span
                                            className={`mt-1.5 h-1.5 w-1.5 rounded-full flex-shrink-0 ${KIND_DOT_CLS[kind] || ""}`}
                                        />
                                        <span className="flex-1 min-w-0">
                                            <span className="block leading-tight">
                                                <span className="text-muted-foreground mr-1">
                                                    {idx + 1}.
                                                </span>
                                                {s.title}
                                            </span>
                                            {(s.connects_to?.length || 0) +
                                                incoming.length >
                                                0 && (
                                                <span className="block text-[10px] text-muted-foreground mt-0.5">
                                                    {incoming.length > 0 && (
                                                        <span>
                                                            ← {incoming.join(", ")}
                                                        </span>
                                                    )}
                                                    {incoming.length > 0 &&
                                                        s.connects_to &&
                                                        s.connects_to.length > 0 &&
                                                        " · "}
                                                    {s.connects_to &&
                                                        s.connects_to.length > 0 && (
                                                            <span>
                                                                → {s.connects_to.join(", ")}
                                                            </span>
                                                        )}
                                                </span>
                                            )}
                                        </span>
                                        <KindIcon className="h-3 w-3 mt-1 text-muted-foreground/60 flex-shrink-0" />
                                    </button>
                                );
                            })}
                        </div>
                    </Card>

                    <div className="space-y-4 min-w-0">
                        {codeBlocks[currentStep]}

                        <div className="flex justify-between">
                            <Button
                                variant="outline"
                                onClick={() => setCurrentStep(currentStep - 1)}
                                disabled={isFirstStep}
                            >
                                <ChevronLeft className="h-4 w-4 mr-2" />
                                Previous
                            </Button>
                            <div className="text-sm text-muted-foreground self-center">
                                Step {currentStep + 1} of {steps.length}
                            </div>
                            <Button
                                onClick={() => setCurrentStep(currentStep + 1)}
                                disabled={isLastStep}
                            >
                                Next
                                <ChevronRight className="h-4 w-4 ml-2" />
                            </Button>
                        </div>
                    </div>
                </div>
            </div>

            <FollowupDialog
                tourId={tour.tour_id}
                stepIndex={currentStep}
                stepTitle={step?.title ?? ""}
                open={followupOpen}
                onOpenChange={setFollowupOpen}
            />
        </div>
    );
}
