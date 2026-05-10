"use client";

import Link from "next/link";
import { ArrowLeft, Terminal } from "lucide-react";

import { LogViewer } from "./LogViewer";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface LogsPageContainerProps {
    streamId: string;
}

export function LogsPageContainer({ streamId }: LogsPageContainerProps) {
    return (
        // RootLayout already renders a sticky global header.
        // Use viewport height minus the global header height (h-14 = 3.5rem)
        // so the log viewer doesn't "fight" the layout and doesn't get covered.
        <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-background">
            {/* page header */}
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

                    <Terminal className="h-4 w-4 text-muted-foreground" />
                    <span className="text-xs font-mono text-muted-foreground">
                        Logs
                    </span>
                    <span className="text-xs font-mono text-muted-foreground/70">
                        {streamId}
                    </span>
                </div>
            </div>

            {/* viewer fills remaining height */}
            <div className="container flex max-w-screen-2xl flex-1 min-h-0 px-4 py-4">
                <LogViewer generationId={streamId} className="h-full w-full" />
            </div>
        </div>
    );
}
