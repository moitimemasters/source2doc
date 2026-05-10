"use client";

import { useState } from "react";
import { PlayCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

interface ResumeFailedButtonProps {
    /** The failed stream's generation_id — also doubles as the streamId. */
    generationId: string;
}

/** Posts to the gateway resume endpoint and stays on the same stream page.
 *
 * Resume re-runs only the failed phase (and everything downstream) by
 * re-emitting the last successful transition event into the per-generation
 * Redis stream. The worker treats the re-emit as a fresh event and
 * dispatches the next-phase handler that previously failed.
 *
 * Because the same ``generation_id`` is reused, there's nowhere new to
 * navigate to — the existing /streams/{id} subscription will pick up the
 * new events as the worker emits them. We just toast and let the live
 * stream UI reflect the status flip from "failed" → "running".
 *
 * On 422 (state expired, no failure event, etc.) the gateway returns a
 * descriptive ``detail``; we surface that as a toast with a hint that
 * the user can fall back to Restart for a from-scratch re-run. */
export function ResumeFailedButton({ generationId }: ResumeFailedButtonProps) {
    const [submitting, setSubmitting] = useState(false);

    const handleClick = async () => {
        if (submitting) return;
        setSubmitting(true);
        try {
            const response = await fetch(
                `/api/gateway/tasks/${encodeURIComponent(generationId)}/resume`,
                { method: "POST" },
            );

            if (!response.ok) {
                let detail = `Resume failed (HTTP ${response.status})`;
                try {
                    const body = await response.json();
                    if (typeof body?.detail === "string") detail = body.detail;
                } catch {
                    // body wasn't JSON — keep the default message
                }
                if (response.status === 422) {
                    toast.error(detail, {
                        description:
                            "State expired or unrecoverable — use Restart instead.",
                    });
                } else {
                    toast.error(detail);
                }
                return;
            }

            const body = await response.json();
            const fromType: string | undefined =
                body?.resumed_from_event?.type;
            toast.success(
                fromType
                    ? `Resuming from ${fromType}`
                    : "Resume queued",
            );
        } catch (err) {
            toast.error(
                err instanceof Error
                    ? err.message
                    : "Failed to resume generation",
            );
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Button
            type="button"
            variant="default"
            onClick={handleClick}
            disabled={submitting}
            data-testid="resume-failed-button"
        >
            <PlayCircle
                className={`h-4 w-4 ${submitting ? "animate-pulse" : ""}`}
            />
            {submitting ? "Resuming..." : "Resume"}
        </Button>
    );
}
