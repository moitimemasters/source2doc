import type { CodetourStep } from "@/lib/codetour-api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { highlightCodeToHtml, getLanguageDisplayName } from "@/lib/wiki/shiki";
import { CodeCopyButton } from "@/components/wiki/blocks/CodeCopyButton";
import {
    AlertTriangle,
    Anchor,
    ArrowRight,
    Flame,
    GitCommit,
    Lightbulb,
    User,
} from "lucide-react";

interface CodeTourStepContentProps {
    step: CodetourStep;
    stepIndex?: number;
    allSteps?: CodetourStep[];
}

function getLanguageFromFile(filename: string): string {
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    const langMap: Record<string, string> = {
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
    return langMap[ext] || "text";
}

const KIND_META: Record<
    string,
    { label: string; icon: any; cls: string }
> = {
    entry: {
        label: "Entry",
        icon: Anchor,
        cls: "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30",
    },
    transition: {
        label: "Transition",
        icon: ArrowRight,
        cls: "bg-muted text-muted-foreground border-border/50",
    },
    leaf: {
        label: "Leaf",
        icon: Flame,
        cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
    },
    gotcha: {
        label: "Gotcha",
        icon: AlertTriangle,
        cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
    },
};

/**
 * Splice the highlights into the syntax-highlighted Shiki HTML.
 * Shiki emits `<span class="line">...</span>` per source line; we wrap each
 * highlighted line with a left-bar marker and a tooltip-like hover note.
 */
function injectHighlights(
    html: string,
    step: CodetourStep,
): string {
    if (!step.highlights || step.highlights.length === 0) return html;
    const baseLine = step.line || 1;

    // Build a map: relative line index (0-based) → note
    const byRelLine = new Map<number, string[]>();
    for (const h of step.highlights) {
        const rel = h.line - baseLine;
        if (rel < 0) continue;
        const list = byRelLine.get(rel) || [];
        list.push(h.note);
        byRelLine.set(rel, list);
    }
    if (byRelLine.size === 0) return html;

    // Replace each <span class="line"> with our wrapped version, indexed by occurrence.
    let idx = -1;
    return html.replace(/<span class="line">/g, () => {
        idx += 1;
        const notes = byRelLine.get(idx);
        if (!notes) return `<span class="line">`;
        const escaped = notes
            .map((n) => n.replace(/"/g, "&quot;").replace(/</g, "&lt;"))
            .join(" • ");
        return `<span class="line s2d-tour-highlight" data-tour-note="${escaped}" title="${escaped}">`;
    });
}

export async function CodeTourStepContent({
    step,
    stepIndex,
    allSteps,
}: CodeTourStepContentProps) {
    const codeContent = step.code || step.pattern;

    const kindMeta = KIND_META[step.kind || "transition"] || KIND_META.transition;
    const KindIcon = kindMeta.icon;

    if (!codeContent) {
        return (
            <Card className="p-6 space-y-4">
                <StepHeader step={step} stepIndex={stepIndex} kindMeta={kindMeta} KindIcon={KindIcon} />
                {step.key_idea && <KeyIdeaCallout idea={step.key_idea} kind={step.kind} />}
                <div className="bg-muted p-4 rounded-md text-sm text-muted-foreground">
                    No code example available for this step.
                </div>
            </Card>
        );
    }

    const lang = getLanguageFromFile(step.file);
    let html = await highlightCodeToHtml(codeContent, lang);
    html = injectHighlights(html, step);

    return (
        <Card className="p-6 space-y-4">
            <StepHeader step={step} stepIndex={stepIndex} kindMeta={kindMeta} KindIcon={KindIcon} />

            {step.key_idea && <KeyIdeaCallout idea={step.key_idea} kind={step.kind} />}

            <div>
                <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-muted-foreground font-mono">
                        {step.file}:{step.line}
                        {step.end_line ? `–${step.end_line}` : ""}
                    </span>
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70 bg-background/80 backdrop-blur-sm px-2 py-0.5 rounded border border-border/30">
                            {getLanguageDisplayName(lang)}
                        </span>
                        <CodeCopyButton code={codeContent} />
                    </div>
                </div>
                <div
                    className="wiki-code overflow-x-auto text-sm leading-6 rounded-lg border border-border/50 bg-muted/30 [&_.s2d-tour-highlight]:relative [&_.s2d-tour-highlight]:bg-amber-500/10 [&_.s2d-tour-highlight]:border-l-2 [&_.s2d-tour-highlight]:border-amber-500/70 [&_.s2d-tour-highlight]:cursor-help"
                    dangerouslySetInnerHTML={{ __html: html }}
                />
            </div>

            {step.highlights && step.highlights.length > 0 && (
                <div className="rounded-md border border-border/50 bg-muted/20 p-3">
                    <div className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">
                        Highlights
                    </div>
                    <ul className="space-y-1.5 text-sm">
                        {step.highlights.map((h, i) => (
                            <li key={i} className="flex items-start gap-2">
                                <span className="text-amber-600 dark:text-amber-400 font-mono text-xs mt-0.5">
                                    L{h.line}
                                </span>
                                <span className="text-foreground/90">{h.note}</span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {step.connects_to && step.connects_to.length > 0 && allSteps && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>Connects to:</span>
                    {step.connects_to.map((idx) => {
                        const target = allSteps[idx];
                        if (!target) return null;
                        return (
                            <a
                                key={idx}
                                href={`#step-${idx}`}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border/50 hover:bg-muted hover:text-foreground transition-colors"
                            >
                                <ArrowRight className="h-3 w-3" />
                                Step {idx + 1}: {target.title}
                            </a>
                        );
                    })}
                </div>
            )}

            <HistoryPanel commits={step.commits} authorship={step.authorship} />
        </Card>
    );
}

function formatRelative(iso?: string | null): string | null {
    if (!iso) return null;
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return null;
    const diffMs = Date.now() - t;
    const day = 24 * 3600 * 1000;
    const days = Math.round(diffMs / day);
    if (days < 1) return "today";
    if (days < 30) return `${days}d ago`;
    const months = Math.round(days / 30);
    if (months < 12) return `${months}mo ago`;
    const years = Math.round(days / 365);
    return `${years}y ago`;
}

function HistoryPanel({
    commits,
    authorship,
}: {
    commits?: CodetourStep["commits"];
    authorship?: CodetourStep["authorship"];
}) {
    const hasCommits = commits && commits.length > 0;
    const hasAuthorship = !!authorship?.primary_author;
    if (!hasCommits && !hasAuthorship) return null;

    return (
        <div className="rounded-md border border-border/50 bg-muted/20 p-3 space-y-3">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                History
            </div>

            {hasAuthorship && authorship && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <span className="inline-flex items-center gap-1.5">
                        <User className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="font-medium">
                            {authorship.primary_author}
                        </span>
                        {typeof authorship.primary_share === "number" && (
                            <span className="text-xs text-muted-foreground">
                                ({Math.round(authorship.primary_share * 100)}%)
                            </span>
                        )}
                    </span>
                    {authorship.last_modified_at && (
                        <span className="text-xs text-muted-foreground">
                            last touched {formatRelative(authorship.last_modified_at) ?? authorship.last_modified_at}
                        </span>
                    )}
                    {authorship.contributors &&
                        authorship.contributors.length > 1 && (
                            <span className="text-xs text-muted-foreground">
                                +
                                {authorship.contributors.length - 1} other
                                contributor
                                {authorship.contributors.length - 1 > 1 ? "s" : ""}
                            </span>
                        )}
                </div>
            )}

            {hasCommits && (
                <ul className="space-y-1.5">
                    {commits!.map((c) => (
                        <li
                            key={c.sha}
                            className="flex items-start gap-2 text-sm"
                        >
                            <GitCommit className="h-3.5 w-3.5 mt-0.5 text-muted-foreground flex-shrink-0" />
                            <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                    <code className="text-xs font-mono text-muted-foreground">
                                        {c.short_sha ?? c.sha.slice(0, 8)}
                                    </code>
                                    {c.author && (
                                        <span className="text-xs text-muted-foreground">
                                            {c.author}
                                        </span>
                                    )}
                                    {c.date && (
                                        <span className="text-xs text-muted-foreground">
                                            · {formatRelative(c.date) ?? c.date}
                                        </span>
                                    )}
                                </div>
                                {c.message && (
                                    <div className="text-foreground/90 break-words">
                                        {c.message}
                                    </div>
                                )}
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

function StepHeader({
    step,
    stepIndex,
    kindMeta,
    KindIcon,
}: {
    step: CodetourStep;
    stepIndex?: number;
    kindMeta: { label: string; cls: string };
    KindIcon: any;
}) {
    return (
        <div className="flex items-start gap-3">
            <Badge
                className={`${kindMeta.cls} border font-normal text-xs flex items-center gap-1 mt-0.5`}
            >
                <KindIcon className="h-3 w-3" />
                {kindMeta.label}
            </Badge>
            <div className="flex-1 min-w-0">
                <h3
                    className="font-semibold text-base"
                    id={
                        typeof stepIndex === "number"
                            ? `step-${stepIndex}`
                            : undefined
                    }
                >
                    {typeof stepIndex === "number" && (
                        <span className="text-muted-foreground mr-2">
                            {stepIndex + 1}.
                        </span>
                    )}
                    {step.title}
                </h3>
                {step.description && (
                    <p className="text-sm text-muted-foreground mt-1">
                        {step.description}
                    </p>
                )}
            </div>
        </div>
    );
}

function KeyIdeaCallout({ idea, kind }: { idea: string; kind?: string }) {
    const isGotcha = kind === "gotcha";
    return (
        <div
            className={`flex items-start gap-2 rounded-md border-l-4 p-3 text-sm ${
                isGotcha
                    ? "border-amber-500 bg-amber-500/10 text-amber-900 dark:text-amber-100"
                    : "border-primary bg-primary/5"
            }`}
        >
            {isGotcha ? (
                <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0 text-amber-600 dark:text-amber-400" />
            ) : (
                <Lightbulb className="h-4 w-4 mt-0.5 flex-shrink-0 text-primary" />
            )}
            <div>
                <div className="text-xs font-semibold uppercase tracking-wider mb-0.5 opacity-70">
                    {isGotcha ? "Watch out" : "Key idea"}
                </div>
                <div>{idea}</div>
            </div>
        </div>
    );
}
