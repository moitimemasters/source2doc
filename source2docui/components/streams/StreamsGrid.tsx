import { StreamInfo } from "@/lib/gateway/types";
import { StreamCard } from "./StreamCard";

interface StreamsGridProps {
    streams: StreamInfo[];
}

export function StreamsGrid({ streams }: StreamsGridProps) {
    return (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {streams.map((stream) => (
                <StreamCard key={stream.stream_id} stream={stream} />
            ))}
        </div>
    );
}
