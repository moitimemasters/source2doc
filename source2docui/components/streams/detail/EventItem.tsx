import { StreamEvent } from "@/lib/gateway/types";
import { getEventIcon, getEventLabel } from "@/lib/gateway/stream-utils";
import { Badge } from "@/components/ui/badge";

interface EventItemProps {
    event: StreamEvent;
    index: number;
}

export function EventItem({ event, index }: EventItemProps) {
    return (
        <div className="flex items-start gap-4 p-4 rounded-lg border bg-card hover:bg-muted/30 transition-colors">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-lg">
                {getEventIcon(event.type)}
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold">{getEventLabel(event.type)}</span>
                    <Badge variant="outline" className="font-mono text-xs">
                        #{index + 1}
                    </Badge>
                </div>
                <div className="text-sm text-muted-foreground font-mono">
                    {event.type}
                </div>
                {event.data && Object.keys(event.data).length > 0 && (
                    <div className="mt-2 text-xs text-muted-foreground">
                        <pre className="bg-muted p-2 rounded overflow-x-auto">
                            {JSON.stringify(event.data, null, 2)}
                        </pre>
                    </div>
                )}
            </div>
        </div>
    );
}
