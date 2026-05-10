"use client";

import { useState } from "react";
import { StopCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

interface StopGenerationButtonProps {
    /** The running stream's generation_id. */
    generationId: string;
}

/** Cancel a running generation.
 *
 * Hits ``POST /api/v1/tasks/{id}/stop`` which flips the worker-side
 * ``state.cancelled`` flag and emits a ``task.failed`` audit marker.
 * In-flight LLM calls finish naturally (we don't abort live httpx
 * requests); subsequent pending events are skip+acked. After the
 * task.failed event lands the UI shows Resume / Restart buttons just
 * like any other failure.
 *
 * Confirms before sending — stopping a long-running generation throws
 * away in-flight LLM tokens, so a single misclick should be hard. */
export function StopGenerationButton({ generationId }: StopGenerationButtonProps) {
    const [submitting, setSubmitting] = useState(false);

    const handleClick = async () => {
        if (submitting) return;
        const ok = window.confirm(
            "Stop this generation? In-flight LLM calls will finish, but " +
                "no new pages will start. You can Resume from the last " +
                "successful checkpoint afterwards.",
        );
        if (!ok) return;

        setSubmitting(true);
        try {
            const response = await fetch(
                `/api/gateway/tasks/${encodeURIComponent(generationId)}/stop`,
                { method: "POST" },
            );

            if (!response.ok) {
                let detail = `Stop failed (HTTP ${response.status})`;
                try {
                    const body = await response.json();
                    if (typeof body?.detail === "string") detail = body.detail;
                } catch {
                    // body wasn't JSON — keep default
                }
                toast.error(detail);
                return;
            }

            toast.success("Cancellation flag set — generation will stop shortly");
        } catch (err) {
            toast.error(
                err instanceof Error
                    ? err.message
                    : "Failed to stop generation",
            );
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleClick}
            disabled={submitting}
            data-testid="stop-generation-button"
        >
            <StopCircle
                className={`h-4 w-4 ${submitting ? "animate-pulse" : ""}`}
            />
            {submitting ? "Stopping..." : "Stop generation"}
        </Button>
    );
}
