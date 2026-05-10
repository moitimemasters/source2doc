import { StreamEvent } from "@/lib/gateway/types";
import { EventItem } from "./EventItem";

interface EventsListProps {
    events: StreamEvent[];
}

export function EventsList({ events }: EventsListProps) {
    if (events.length === 0) {
        return (
            <div className="text-center py-8 text-muted-foreground">
                No events yet. Waiting for stream to start...
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {events.map((event, index) => (
                <EventItem key={event.id || `event-${index}`} event={event} index={index} />
            ))}
        </div>
    );
}
