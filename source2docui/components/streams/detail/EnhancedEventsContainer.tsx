"use client";

import { useState, useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { StreamEvent } from "@/lib/gateway/types";
import {
    EventFilterState,
    DEFAULT_FILTERS,
    dropHeartbeats,
    filterEvents,
    getAvailablePhases,
    getAvailableEventTypes,
} from "@/lib/streams/event-filters";
import { groupEventsByPhase } from "@/lib/streams/event-grouping";
import { FilterBar } from "./filters/FilterBar";
import { EventGroup } from "./events/EventGroup";
import { EventStats } from "./events/EventStats";
import { EnhancedEventItem } from "./events/EnhancedEventItem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface EnhancedEventsContainerProps {
    events: StreamEvent[];
}

// Virtualized event list. Renders only the rows currently in the viewport
// (plus a small overscan window) so a 5000-event generation doesn't push
// 5000 EnhancedEventItem subtrees into the DOM. Estimated row height is a
// guess; the virtualizer measures actual heights on first render and uses
// those for subsequent layouts.
function VirtualizedEventList({ events }: { events: StreamEvent[] }) {
    const parentRef = useRef<HTMLDivElement | null>(null);
    const virtualizer = useVirtualizer({
        count: events.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 64,
        overscan: 8,
    });
    const items = virtualizer.getVirtualItems();
    const totalSize = virtualizer.getTotalSize();
    return (
        <div
            ref={parentRef}
            className="h-[640px] overflow-auto"
            style={{ contain: "strict" }}
        >
            <div
                style={{
                    height: totalSize,
                    width: "100%",
                    position: "relative",
                }}
            >
                {items.map((virtualRow) => {
                    const event = events[virtualRow.index];
                    return (
                        <div
                            key={event.id || `event-${virtualRow.index}`}
                            ref={virtualizer.measureElement}
                            data-index={virtualRow.index}
                            style={{
                                position: "absolute",
                                top: 0,
                                left: 0,
                                right: 0,
                                transform: `translateY(${virtualRow.start}px)`,
                                paddingBottom: 8,
                            }}
                        >
                            <EnhancedEventItem
                                event={event}
                                index={virtualRow.index}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export function EnhancedEventsContainer({
    events,
}: EnhancedEventsContainerProps) {
    const [filters, setFilters] = useState<EventFilterState>(DEFAULT_FILTERS);
    const [viewMode, setViewMode] = useState<"grouped" | "list">("grouped");

    const visibleEvents = useMemo(() => dropHeartbeats(events), [events]);

    const availablePhases = useMemo(
        () => getAvailablePhases(visibleEvents),
        [visibleEvents],
    );

    const availableEventTypes = useMemo(
        () => getAvailableEventTypes(visibleEvents),
        [visibleEvents],
    );

    const filteredEvents = useMemo(
        () => filterEvents(visibleEvents, filters),
        [visibleEvents, filters],
    );

    const groupedEvents = useMemo(
        () => groupEventsByPhase(filteredEvents),
        [filteredEvents],
    );

    if (visibleEvents.length === 0) {
        return (
            <Card>
                <CardContent className="py-12">
                    <div className="text-center text-muted-foreground">
                        No events yet. Waiting for stream to start...
                    </div>
                </CardContent>
            </Card>
        );
    }

    return (
        <div className="space-y-4">
            <div className="flex gap-4">
                <div className="flex-1">
                    <FilterBar
                        filters={filters}
                        onFiltersChange={setFilters}
                        availablePhases={availablePhases}
                        availableEventTypes={availableEventTypes}
                        totalEvents={visibleEvents.length}
                        filteredEvents={filteredEvents.length}
                    />
                </div>
                <div className="w-64 flex-shrink-0">
                    <EventStats events={filteredEvents} />
                </div>
            </div>

            <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as any)}>
                <TabsList className="grid w-full max-w-xs grid-cols-2 font-mono text-xs h-8">
                    <TabsTrigger value="grouped" className="text-xs">
                        Grouped
                    </TabsTrigger>
                    <TabsTrigger value="list" className="text-xs">
                        Flat List
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="grouped" className="space-y-3 mt-4">
                    {groupedEvents.length === 0 ? (
                        <Card>
                            <CardContent className="py-12">
                                <div className="text-center text-muted-foreground">
                                    No events match the current filters
                                </div>
                            </CardContent>
                        </Card>
                    ) : (
                        groupedEvents.map((group) => (
                            <EventGroup
                                key={group.phase}
                                phase={group.phase}
                                events={group.events}
                            />
                        ))
                    )}
                </TabsContent>

                <TabsContent value="list" className="mt-4">
                    <Card className="font-mono">
                        <CardHeader className="pb-3">
                            <CardTitle className="text-sm font-semibold">
                                All Events
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="p-3">
                            {filteredEvents.length === 0 ? (
                                <div className="text-center py-8 text-muted-foreground">
                                    No events match the current filters
                                </div>
                            ) : (
                                <VirtualizedEventList events={filteredEvents} />
                            )}
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>
        </div>
    );
}
