import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { X } from "lucide-react";
import { SearchInput } from "./SearchInput";
import { PhaseFilter } from "./PhaseFilter";
import { EventTypeFilter } from "./EventTypeFilter";
import { EventFilterState } from "@/lib/streams/event-filters";

interface FilterBarProps {
    filters: EventFilterState;
    onFiltersChange: (filters: EventFilterState) => void;
    availablePhases: string[];
    availableEventTypes: string[];
    totalEvents: number;
    filteredEvents: number;
}

export function FilterBar({
    filters,
    onFiltersChange,
    availablePhases,
    availableEventTypes,
    totalEvents,
    filteredEvents,
}: FilterBarProps) {
    const hasActiveFilters =
        filters.search ||
        filters.phase !== "all" ||
        filters.eventType !== "all";

    const clearFilters = () => {
        onFiltersChange({ search: "", phase: "all", eventType: "all" });
    };

    return (
        <div className="space-y-2 font-mono">
            <div className="flex flex-col sm:flex-row gap-2">
                <SearchInput
                    value={filters.search}
                    onChange={(value) =>
                        onFiltersChange({ ...filters, search: value })
                    }
                    placeholder="Search events..."
                />

                <PhaseFilter
                    value={filters.phase}
                    onChange={(value) =>
                        onFiltersChange({ ...filters, phase: value })
                    }
                    phases={availablePhases}
                />

                <EventTypeFilter
                    value={filters.eventType}
                    onChange={(value) =>
                        onFiltersChange({ ...filters, eventType: value })
                    }
                    eventTypes={availableEventTypes}
                />

                {hasActiveFilters && (
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={clearFilters}
                        title="Clear filters"
                        className="h-9"
                    >
                        <X className="h-3.5 w-3.5" />
                    </Button>
                )}
            </div>

            <div className="flex items-center justify-between text-xs text-muted-foreground">
                <div>
                    {filteredEvents} / {totalEvents} events
                </div>
                {hasActiveFilters && (
                    <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                        Filtered
                    </Badge>
                )}
            </div>
        </div>
    );
}
