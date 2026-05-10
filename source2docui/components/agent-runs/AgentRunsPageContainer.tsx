"use client";

import Link from "next/link";
import { ArrowLeft, MessagesSquare } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { AgentRunsTable } from "./AgentRunsTable";

interface AgentRunsPageContainerProps {
    streamId: string;
}

export function AgentRunsPageContainer({
    streamId,
}: AgentRunsPageContainerProps) {
    return (
        <div className="flex min-h-[calc(100vh-3.5rem)] flex-col bg-background">
            <div className="shrink-0 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
                <div className="container flex h-12 max-w-screen-2xl items-center gap-3 px-4">
                    <Button
                        asChild
                        variant="ghost"
                        size="sm"
                        className="gap-2 font-mono text-xs"
                    >
                        <Link href={`/streams/${streamId}`}>
                            <ArrowLeft className="h-4 w-4" />
                            Back to stream
                        </Link>
                    </Button>
                    <Separator orientation="vertical" className="h-6" />
                    <MessagesSquare className="h-4 w-4 text-muted-foreground" />
                    <span className="text-xs font-mono text-muted-foreground">
                        Agent runs
                    </span>
                    <span className="text-xs font-mono text-muted-foreground/70">
                        {streamId}
                    </span>
                </div>
            </div>

            <div className="container flex flex-col max-w-screen-2xl flex-1 min-h-0 px-4 py-4 gap-4">
                <p className="text-xs text-muted-foreground">
                    Every Pydantic-AI agent invocation in this generation
                    (planner, subplanner, writer, critic, diagrammer) is
                    recorded here. Click any row to inspect the full message
                    history, tool calls, tool results, and structured output.
                </p>
                <AgentRunsTable generationId={streamId} />
            </div>
        </div>
    );
}
