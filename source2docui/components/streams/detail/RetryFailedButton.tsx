"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

interface RetryFailedButtonProps {
    /** The failed stream's generation_id — also doubles as the streamId. */
    generationId: string;
}

/** Posts to the gateway retry endpoint and navigates to the new stream.
 *
 * "Restart" semantic: the gateway re-encrypts the original task config
 * under a *fresh* generation_id and xadd's a new ``task.created`` onto
 * ``tasks:docgen``. The whole pipeline runs from scratch (B2.4 ingest
 * cache still saves embedding cost when file hashes are unchanged).
 *
 * Used as a fallback when Resume can't (state expired, ingest itself
 * failed, etc.). For partial-failure resume — the common case — see
 * ``ResumeFailedButton`` which is the primary action.
 *
 * On 422 the original payload is unrecoverable (DLQ trim or expired
 * ``config:{id}`` blob) — surface that as a toast. */
export function RetryFailedButton({ generationId }: RetryFailedButtonProps) {
    const router = useRouter();
    const [submitting, setSubmitting] = useState(false);

    const handleClick = async () => {
        if (submitting) return;
        setSubmitting(true);
        try {
            const response = await fetch(
                `/api/gateway/tasks/${encodeURIComponent(generationId)}/retry`,
                { method: "POST" },
            );

            if (!response.ok) {
                let detail = `Restart failed (HTTP ${response.status})`;
                try {
                    const body = await response.json();
                    if (typeof body?.detail === "string") detail = body.detail;
                } catch {
                    // body wasn't JSON — keep the default message
                }
                toast.error(detail);
                return;
            }

            const body = await response.json();
            const newId: string | undefined = body?.generation_id;
            if (!newId) {
                toast.error(
                    "Restart succeeded but no generation_id was returned",
                );
                return;
            }
            toast.success("Restart queued");
            router.push(`/streams/${newId}`);
        } catch (err) {
            toast.error(
                err instanceof Error
                    ? err.message
                    : "Failed to restart generation",
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
            data-testid="retry-failed-button"
        >
            <RefreshCw
                className={`h-4 w-4 ${submitting ? "animate-spin" : ""}`}
            />
            {submitting ? "Restarting..." : "Restart"}
        </Button>
    );
}
