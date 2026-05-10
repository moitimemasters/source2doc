import { Badge } from "@/components/ui/badge";
import { Activity, CheckCircle2 } from "lucide-react";
import { StreamInfo } from "@/lib/gateway/types";

interface StreamsHeaderProps {
    streams: StreamInfo[];
}

export function StreamsHeader({ streams }: StreamsHeaderProps) {
    const activeCount = streams.filter(
        (s) => s.status === "running" || s.status === "pending" || !s.status,
    ).length;
    const doneCount = streams.filter(
        (s) => s.status === "completed",
    ).length;

    return (
        <div className="mb-12">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-4xl font-bold tracking-tight mb-2">
                        Generation Streams
                    </h1>
                    <p className="text-xl text-muted-foreground">
                        Monitor documentation generation processes
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {activeCount > 0 && (
                        <Badge variant="default" className="text-sm px-3 py-1.5 bg-blue-500/15 text-blue-600 border-blue-500/30 dark:text-blue-400">
                            <Activity className="h-3.5 w-3.5 mr-1.5 animate-pulse" />
                            {activeCount} Active
                        </Badge>
                    )}
                    {doneCount > 0 && (
                        <Badge variant="outline" className="text-sm px-3 py-1.5 bg-green-500/15 text-green-600 border-green-500/30 dark:text-green-400">
                            <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                            {doneCount} Done
                        </Badge>
                    )}
                    {streams.length === 0 && (
                        <Badge variant="secondary" className="text-sm px-3 py-1.5">
                            <Activity className="h-3.5 w-3.5 mr-1.5" />
                            No streams
                        </Badge>
                    )}
                </div>
            </div>
        </div>
    );
}
