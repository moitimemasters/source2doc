import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getPhaseStats } from "@/lib/streams/event-grouping";
import { getPhaseLabel, getPhaseIcon } from "@/lib/streams/event-grouping";
import { StreamEvent } from "@/lib/gateway/types";
import * as LucideIcons from "lucide-react";

interface EventStatsProps {
    events: StreamEvent[];
}

export function EventStats({ events }: EventStatsProps) {
    const stats = getPhaseStats(events);

    return (
        <Card className="font-mono">
            <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold">
                    Statistics
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
                <div className="flex items-center justify-between p-2 bg-muted rounded text-sm">
                    <span className="font-medium">Total</span>
                    <span className="font-bold">{stats.total}</span>
                </div>

                <div className="space-y-1">
                    {Object.entries(stats.byPhase)
                        .sort(([, a], [, b]) => b - a)
                        .map(([phase, count]) => {
                            const iconName = getPhaseIcon(phase);
                            const IconComponent =
                                (LucideIcons as any)[iconName] ||
                                LucideIcons.Circle;
                            return (
                                <div
                                    key={phase}
                                    className="flex items-center justify-between p-1.5 hover:bg-muted/50 rounded transition-colors text-xs"
                                >
                                    <div className="flex items-center gap-1.5">
                                        <IconComponent className="h-3 w-3 text-muted-foreground" />
                                        <span className="text-muted-foreground">
                                            {getPhaseLabel(phase)}
                                        </span>
                                    </div>
                                    <span className="font-semibold">{count}</span>
                                </div>
                            );
                        })}
                </div>
            </CardContent>
        </Card>
    );
}
