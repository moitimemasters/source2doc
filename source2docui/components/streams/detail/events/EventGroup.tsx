"use client";

import { useState, useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { StreamEvent } from "@/lib/gateway/types";
import { collapseConsecutiveEvents } from "@/lib/streams/event-collapsing";
import { EventGroupHeader } from "./EventGroupHeader";
import { EnhancedEventItem } from "./EnhancedEventItem";

interface EventGroupProps {
    phase: string;
    events: StreamEvent[];
    initialExpanded?: boolean;
}

// When expanded a phase can hold hundreds of events for long generations.
// Render via virtualization once we exceed this threshold; below it the
// classic ``.map`` keeps the markup simple and avoids a height-measurement
// flash on tiny groups.
const VIRTUALIZE_AFTER = 30;

export function EventGroup({
    phase,
    events,
    initialExpanded = false,
}: EventGroupProps) {
    const [isExpanded, setIsExpanded] = useState(initialExpanded);

    const collapsedEvents = useMemo(
        () => collapseConsecutiveEvents(events),
        [events],
    );

    return (
        <div className="border rounded overflow-hidden bg-card">
            <EventGroupHeader
                phase={phase}
                eventCount={events.length}
                isExpanded={isExpanded}
                onToggle={() => setIsExpanded(!isExpanded)}
            />

            {isExpanded && (
                <div className="border-t">
                    {collapsedEvents.length > VIRTUALIZE_AFTER ? (
                        <VirtualizedCollapsedList events={collapsedEvents} />
                    ) : (
                        <div className="p-2 space-y-2">
                            {collapsedEvents.map((collapsedEvent, index) => (
                                <EnhancedEventItem
                                    key={`collapsed-${index}`}
                                    event={collapsedEvent}
                                    index={collapsedEvent.startIndex}
                                />
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function VirtualizedCollapsedList({
    events,
}: {
    events: ReturnType<typeof collapseConsecutiveEvents>;
}) {
    const parentRef = useRef<HTMLDivElement | null>(null);
    const virtualizer = useVirtualizer({
        count: events.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 56,
        overscan: 8,
    });
    return (
        <div
            ref={parentRef}
            className="h-[480px] overflow-auto p-2"
            style={{ contain: "strict" }}
        >
            <div
                style={{
                    height: virtualizer.getTotalSize(),
                    width: "100%",
                    position: "relative",
                }}
            >
                {virtualizer.getVirtualItems().map((row) => {
                    const event = events[row.index];
                    return (
                        <div
                            key={`collapsed-${row.index}`}
                            ref={virtualizer.measureElement}
                            data-index={row.index}
                            style={{
                                position: "absolute",
                                top: 0,
                                left: 0,
                                right: 0,
                                transform: `translateY(${row.start}px)`,
                                paddingBottom: 8,
                            }}
                        >
                            <EnhancedEventItem
                                event={event}
                                index={event.startIndex}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
