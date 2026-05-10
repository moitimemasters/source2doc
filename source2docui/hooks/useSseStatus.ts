"use client";

import { useAppSelector } from "@/lib/store/hooks";
import type { SseStatus } from "@/lib/store/streams-slice";

export interface SseStatusResult {
    status: SseStatus;
    lastEventTs: number | null;
}

/**
 * Returns the current SSE connection status for a stream tracked by the
 * streams slice. Falls back to `connecting` when the stream entry is not
 * yet in the store (e.g. between mount and the first dispatch).
 */
export function useSseStatus(streamId: string | null | undefined): SseStatusResult {
    return useAppSelector((state) => {
        if (!streamId) {
            return { status: "connecting" as SseStatus, lastEventTs: null };
        }
        const stream = state.streams.streams[streamId];
        if (!stream) {
            return { status: "connecting" as SseStatus, lastEventTs: null };
        }
        return {
            status: stream.sseStatus,
            lastEventTs: stream.lastEventTs,
        };
    });
}
