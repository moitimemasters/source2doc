"use client";

import { UseFormReturn } from "react-hook-form";
import { useBundlesList } from "@/lib/bundles/use-bundles-list";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import {
    BundleExportFormData,
    MERMAID_RENDER_OPTIONS,
    SUPPORTED_FORMATS,
} from "@/lib/bundles/schema";
import { Package } from "lucide-react";

interface BundleConfigSectionProps {
    form: UseFormReturn<BundleExportFormData>;
}

export function BundleConfigSection({ form }: BundleConfigSectionProps) {
    const {
        formState: { errors },
        setValue,
        watch,
    } = form;

    const format = watch("format");
    const generationId = watch("generationId");
    const mermaidRender = watch("mermaidRender");

    const { bundles, loading, error: loadError } = useBundlesList();

    function handleBundleChange(value: string) {
        const bundle = bundles.find((b) => b.generation_id === value);
        if (!bundle) return;
        setValue("generationId", bundle.generation_id);
        setValue("bundleId", bundle.id);
    }

    return (
        <Card>
            <CardHeader>
                <div className="flex items-center gap-2">
                    <Package className="h-5 w-5 text-primary" />
                    <CardTitle>Bundle Export Configuration</CardTitle>
                </div>
                <CardDescription>
                    Export a generated documentation bundle to a specific format
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="space-y-2">
                    <Label htmlFor="bundle">Bundle *</Label>
                    <Select
                        value={generationId}
                        onValueChange={handleBundleChange}
                        disabled={loading || !!loadError}
                    >
                        <SelectTrigger id="bundle">
                            <SelectValue
                                placeholder={
                                    loading
                                        ? "Loading bundles…"
                                        : bundles.length === 0
                                          ? "No completed bundles yet"
                                          : "Pick a bundle"
                                }
                            />
                        </SelectTrigger>
                        <SelectContent>
                            {bundles.map((b) => {
                                const label =
                                    b.name ||
                                    b.repository?.name ||
                                    b.project_name ||
                                    `Bundle #${b.id}`;
                                const dateStr = b.created_at
                                    ? new Date(b.created_at).toLocaleString(
                                          "en-US",
                                          {
                                              month: "short",
                                              day: "numeric",
                                              hour: "2-digit",
                                              minute: "2-digit",
                                          },
                                      )
                                    : null;
                                const total = b.pages_count ?? 0;
                                const failed = b.failed_pages_count ?? 0;
                                const success =
                                    b.successful_pages_count ?? total - failed;
                                const pagesStr =
                                    total > 0
                                        ? failed > 0
                                            ? `${success}/${total} pages`
                                            : `${total} pages`
                                        : null;
                                const subline = [dateStr, pagesStr]
                                    .filter(Boolean)
                                    .join(" · ");
                                return (
                                    <SelectItem
                                        key={b.generation_id}
                                        value={b.generation_id}
                                    >
                                        <div className="flex flex-col">
                                            <span>{label}</span>
                                            {subline && (
                                                <span className="text-xs text-muted-foreground">
                                                    {subline}
                                                </span>
                                            )}
                                        </div>
                                    </SelectItem>
                                );
                            })}
                        </SelectContent>
                    </Select>
                    {loadError && (
                        <p className="text-sm text-destructive">
                            Failed to load bundles: {loadError}
                        </p>
                    )}
                    {(errors.generationId || errors.bundleId) && (
                        <p className="text-sm text-destructive">
                            {errors.generationId?.message ||
                                errors.bundleId?.message}
                        </p>
                    )}
                </div>

                <div className="space-y-2">
                    <Label htmlFor="format">Output Format *</Label>
                    <Select
                        value={format}
                        onValueChange={(value) =>
                            setValue("format", value as any)
                        }
                    >
                        <SelectTrigger id="format">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {SUPPORTED_FORMATS.map((fmt) => (
                                <SelectItem key={fmt.value} value={fmt.value}>
                                    <div className="flex flex-col">
                                        <span>{fmt.label}</span>
                                        <span className="text-xs text-muted-foreground">
                                            {fmt.description}
                                        </span>
                                    </div>
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    {errors.format && (
                        <p className="text-sm text-destructive">
                            {errors.format.message}
                        </p>
                    )}
                </div>

                <div className="space-y-2">
                    <Label htmlFor="mermaid-render">Mermaid Diagrams</Label>
                    <Select
                        value={mermaidRender}
                        onValueChange={(value) =>
                            setValue("mermaidRender", value as any)
                        }
                    >
                        <SelectTrigger id="mermaid-render">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {MERMAID_RENDER_OPTIONS.map((opt) => (
                                <SelectItem key={opt.value} value={opt.value}>
                                    <div className="flex flex-col">
                                        <span>{opt.label}</span>
                                        <span className="text-xs text-muted-foreground">
                                            {opt.description}
                                        </span>
                                    </div>
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                    {errors.mermaidRender && (
                        <p className="text-sm text-destructive">
                            {errors.mermaidRender.message}
                        </p>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
