"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import {
    bundleExportSchema,
    defaultBundleExportValues,
    BundleExportFormData,
} from "@/lib/bundles/schema";
import { BundleConfigSection } from "./BundleConfigSection";
import { toast } from "sonner";
import { BundleExportsSection } from "./BundleExportsSection";

export function BundleExportFormContainer() {
    const router = useRouter();
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState(false);

    const form = useForm<BundleExportFormData>({
        resolver: zodResolver(bundleExportSchema),
        defaultValues: defaultBundleExportValues,
    });

    const onSubmit = async (data: BundleExportFormData) => {
        setIsSubmitting(true);
        setError(null);
        setSuccess(false);

        try {
            const payload: Record<string, unknown> = {
                bundle_id: data.bundleId,
                generation_id: data.generationId,
                format: data.format,
                channel: data.channel,
            };
            if (data.mermaidRender && data.mermaidRender !== "default") {
                payload.mermaid_render = data.mermaidRender;
            }

            const response = await fetch("/api/gateway/bundles/export", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(
                    errorData.detail || "Failed to create bundle export task",
                );
            }

            const result = await response.json();
            setSuccess(true);
            toast.success(
                result.message || "Bundle export task created successfully!",
            );

            // Reset form after 3 seconds
            setTimeout(() => {
                form.reset();
                setSuccess(false);
            }, 3000);
        } catch (err) {
            const errorMessage =
                err instanceof Error ? err.message : "An error occurred";
            setError(errorMessage);
            toast.error(errorMessage);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="space-y-8">
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                <div className="flex justify-between items-center">
                    <h2 className="text-2xl font-bold">Export Bundle</h2>
                </div>

                {error && (
                    <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription>{error}</AlertDescription>
                    </Alert>
                )}

                {success && (
                    <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
                        <CheckCircle2 className="h-4 w-4 text-green-600" />
                        <AlertDescription className="text-green-600">
                            Bundle export task created successfully!
                        </AlertDescription>
                    </Alert>
                )}

                <BundleConfigSection form={form} />

                <Separator />

                <div className="flex justify-end gap-4">
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => router.push("/")}
                        disabled={isSubmitting}
                    >
                        Cancel
                    </Button>
                    <Button type="submit" disabled={isSubmitting}>
                        {isSubmitting && (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        )}
                        {isSubmitting
                            ? "Creating Export Task..."
                            : "Export Bundle"}
                    </Button>
                </div>
            </form>

            <BundleExportsSection />
        </div>
    );
}
