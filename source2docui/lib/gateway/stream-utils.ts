export { getEventIcon, getEventLabel } from "@/lib/pipelines/event-display";

export function formatDuration(start?: number, end?: number): string {
    if (start === undefined) return "—";

    const endTime = end ?? Date.now();
    const duration = endTime - start;

    const seconds = Math.floor(duration / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
        return `${hours}h ${minutes % 60}m`;
    } else if (minutes > 0) {
        return `${minutes}m ${seconds % 60}s`;
    } else {
        return `${seconds}s`;
    }
}
