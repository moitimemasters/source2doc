"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { codetourAPI } from "@/lib/codetour-api";
import { Loader2 } from "lucide-react";

interface FollowupDialogProps {
    tourId: string;
    stepIndex: number;
    stepTitle: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

export function FollowupDialog({
    tourId,
    stepIndex,
    stepTitle,
    open,
    onOpenChange,
}: FollowupDialogProps) {
    const router = useRouter();
    const [question, setQuestion] = useState("");
    const [maxNewSteps, setMaxNewSteps] = useState(3);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [pendingRequestId, setPendingRequestId] = useState<string | null>(
        null,
    );

    useEffect(() => {
        if (open) {
            setError(null);
            setPendingRequestId(null);
        }
    }, [open]);

    useEffect(() => {
        if (!pendingRequestId) return;
        const unsubscribe = codetourAPI.subscribeToTourStream(
            tourId,
            (type, data) => {
                if (
                    (type === "codetour.followup_completed" ||
                        type === "codetour.followup_failed") &&
                    data?.request_id === pendingRequestId
                ) {
                    setSubmitting(false);
                    setPendingRequestId(null);
                    if (type === "codetour.followup_failed") {
                        setError(data?.error ?? "Follow-up failed");
                    } else {
                        onOpenChange(false);
                        router.refresh();
                    }
                }
            },
        );
        return unsubscribe;
    }, [pendingRequestId, tourId, router, onOpenChange]);

    async function onSubmit(e: React.FormEvent) {
        e.preventDefault();
        setError(null);
        setSubmitting(true);
        try {
            const resp = await codetourAPI.requestFollowup(tourId, {
                step_index: stepIndex,
                question,
                max_new_steps: maxNewSteps,
            });
            setPendingRequestId(resp.request_id);
        } catch (err) {
            setError((err as Error).message);
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>Ask follow-up</DialogTitle>
                    <DialogDescription>
                        Anchored at step {stepIndex + 1}: {stepTitle}
                    </DialogDescription>
                </DialogHeader>
                <form className="space-y-4" onSubmit={onSubmit}>
                    <div className="space-y-2">
                        <Label htmlFor="followup-question">Your question</Label>
                        <Textarea
                            id="followup-question"
                            value={question}
                            onChange={(e) => setQuestion(e.target.value)}
                            placeholder="e.g. What happens if the cache is cold and the worker crashes between steps 3 and 5?"
                            rows={3}
                            required
                            disabled={submitting}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label htmlFor="followup-max">Max new steps</Label>
                        <Input
                            id="followup-max"
                            type="number"
                            min={1}
                            max={8}
                            value={maxNewSteps}
                            onChange={(e) =>
                                setMaxNewSteps(Number(e.target.value))
                            }
                            disabled={submitting}
                        />
                    </div>
                    {error && (
                        <p className="text-sm text-destructive">{error}</p>
                    )}
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="ghost"
                            onClick={() => onOpenChange(false)}
                            disabled={submitting}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={submitting || question.trim().length < 3}>
                            {submitting && (
                                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                            )}
                            {submitting ? "Generating…" : "Generate"}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}
