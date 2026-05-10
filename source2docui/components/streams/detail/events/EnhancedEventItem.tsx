"use client";

import { useState } from "react";
import { StreamEvent } from "@/lib/gateway/types";
import { getEventLabel, getEventIcon } from "@/lib/gateway/stream-utils";
import {
    getEventSummary,
    shouldShowDataInline,
    getEventColor,
} from "@/lib/streams/event-formatting";
import { CollapsedEvent } from "@/lib/streams/event-collapsing";
import { SingleEventItem } from "./SingleEventItem";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight } from "lucide-react";
import * as LucideIcons from "lucide-react";

interface EnhancedEventItemProps {
    event: StreamEvent | CollapsedEvent;
    index: number;
}

function isCollapsedEvent(
    event: StreamEvent | CollapsedEvent,
): event is CollapsedEvent {
    return "count" in event && "events" in event;
}

export function EnhancedEventItem({ event, index }: EnhancedEventItemProps) {
    const [isExpanded, setIsExpanded] = useState(false);

    const isCollapsed = isCollapsedEvent(event);

    // If it's a single event, use SingleEventItem
    if (!isCollapsed) {
        return <SingleEventItem event={event} index={index} />;
    }

    // For collapsed events with count > 1
    if (event.count === 1) {
        return <SingleEventItem event={event.events[0]} index={event.startIndex} />;
    }

    const eventType = event.type;
    const eventData = event.data;
    const summary = getEventSummary({ type: eventType, data: eventData || {} } as StreamEvent);
    const colorClass = getEventColor(eventType);

    const iconName = getEventIcon(eventType);
    const IconComponent = (LucideIcons as any)[iconName] || LucideIcons.Circle;

    return (
        <div className="rounded border bg-card font-mono text-sm">
            <div
                className="flex items-start gap-2.5 p-2.5 hover:bg-muted/30 transition-colors cursor-pointer"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className="flex-shrink-0 mt-0.5">
                    <IconComponent className={`h-3.5 w-3.5 ${colorClass}`} />
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                        <span className={`font-semibold text-xs ${colorClass}`}>
                            {getEventLabel(eventType)}
                        </span>
                        <Badge variant="outline" className="text-[10px] h-4 px-1">
                            x{event.count} #{event.startIndex + 1}-#{event.endIndex + 1}
                        </Badge>
                    </div>

                    <div className="text-xs text-muted-foreground">
                        {summary}
                    </div>
                </div>

                <div className="flex-shrink-0 text-muted-foreground mt-0.5">
                    {isExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                        <ChevronRight className="h-3.5 w-3.5" />
                    )}
                </div>
            </div>

            {isExpanded && (
                <div className="px-2.5 pb-2 pt-0 border-t space-y-2">
                    {event.events.map((evt, idx) => (
                        <SingleEventItem
                            key={evt.id || `sub-${idx}`}
                            event={evt}
                            index={event.startIndex + idx}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
