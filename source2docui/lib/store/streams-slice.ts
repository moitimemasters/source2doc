import { createSlice, PayloadAction } from "@reduxjs/toolkit";
import { StreamEvent, StreamInfo } from "@/lib/gateway/types";

// SSE connection lifecycle exposed to the UI. `connecting` covers both the
// initial connect attempt and any reconnect window; `connected` flips to
// `disconnected` if no event/ping arrives within the staleness threshold.
export type SseStatus = "connecting" | "connected" | "disconnected";

export interface StreamState {
    streamId: string;
    info: StreamInfo;
    events: StreamEvent[];
    isConnected: boolean;
    error: string | null;
    sseStatus: SseStatus;
    lastEventTs: number | null;
    // Per-task correlation token populated from the FIRST event observed
    // (gateway stamps `trace_id` on every payload). Never overwritten on
    // subsequent events so the value matches what the gateway returned in
    // the original task-creation response.
    traceId: string | null;
}

export interface StreamsState {
    streams: Record<string, StreamState>;
    streamsList: StreamInfo[];
    isLoadingList: boolean;
    listError: string | null;
    activeStreamId: string | null;
}

const initialState: StreamsState = {
    streams: {},
    streamsList: [],
    isLoadingList: false,
    listError: null,
    activeStreamId: null,
};

const streamsSlice = createSlice({
    name: "streams",
    initialState,
    reducers: {
        // List streams actions
        fetchStreamsList: (state) => {
            state.isLoadingList = true;
            state.listError = null;
        },
        fetchStreamsListSuccess: (
            state,
            action: PayloadAction<StreamInfo[]>,
        ) => {
            state.streamsList = action.payload;
            state.isLoadingList = false;
            state.listError = null;
        },
        fetchStreamsListFailure: (state, action: PayloadAction<string>) => {
            state.isLoadingList = false;
            state.listError = action.payload;
        },

        // Connect to stream
        connectToStream: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (!state.streams[streamId]) {
                const decodedStreamId = decodeURIComponent(streamId);
                state.streams[streamId] = {
                    streamId,
                    info: {
                        stream_id: decodedStreamId,
                        pipeline_id: decodedStreamId.startsWith("codetour:")
                            ? "codetour"
                            : "docgen",
                        event_count: 0,
                        last_event_id: null,
                    },
                    events: [],
                    isConnected: false,
                    error: null,
                    sseStatus: "connecting",
                    lastEventTs: null,
                    traceId: null,
                };
            } else {
                // Re-using an existing entry on reconnect: drop back to
                // `connecting` so the indicator reflects the new attempt.
                state.streams[streamId].sseStatus = "connecting";
            }
            state.activeStreamId = streamId;
        },

        // Stream connection status
        streamConnecting: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].sseStatus = "connecting";
            }
        },
        streamConnected: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].isConnected = true;
                state.streams[streamId].error = null;
                state.streams[streamId].sseStatus = "connected";
                state.streams[streamId].lastEventTs = Date.now();
            }
        },
        streamDisconnected: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].isConnected = false;
                state.streams[streamId].sseStatus = "disconnected";
            }
        },
        streamStale: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (
                state.streams[streamId] &&
                state.streams[streamId].sseStatus === "connected"
            ) {
                state.streams[streamId].sseStatus = "disconnected";
            }
        },
        streamError: (
            state,
            action: PayloadAction<{ streamId: string; error: string }>,
        ) => {
            const { streamId, error } = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].error = error;
                state.streams[streamId].isConnected = false;
                state.streams[streamId].sseStatus = "disconnected";
            }
        },

        // Stream events
        streamEventReceived: (
            state,
            action: PayloadAction<{ streamId: string; event: StreamEvent }>,
        ) => {
            const { streamId, event } = action.payload;
            if (state.streams[streamId]) {
                // Drop duplicates: the gateway's SSE generator replays the
                // stream from "0" so anything we already loaded via the
                // REST `/events` historical fetch reappears here. Skip if
                // we've already seen this event id.
                const existing = state.streams[streamId].events;
                if (event.id && existing.some((e) => e.id === event.id)) {
                    state.streams[streamId].lastEventTs = Date.now();
                    state.streams[streamId].sseStatus = "connected";
                    return;
                }
                existing.push(event);
                state.streams[streamId].info.event_count += 1;
                state.streams[streamId].info.last_event_id = event.id;
                state.streams[streamId].lastEventTs = Date.now();
                state.streams[streamId].sseStatus = "connected";

                // Capture trace_id from the first event that carries one.
                // The gateway stamps it on every payload so any event will
                // do, but we only set it once so reconnects don't churn.
                if (
                    state.streams[streamId].traceId === null &&
                    typeof event.trace_id === "string" &&
                    event.trace_id.length > 0
                ) {
                    state.streams[streamId].traceId = event.trace_id;
                }

                // Keep stream "status" purely derived from the LATEST
                // event we've seen. Newest wins so that:
                //   * ``generation.completed`` flips status to "completed";
                //   * ``task.failed`` / ``step.failed`` / ``generation.failed``
                //     flip to "failed" (retry / resume buttons surface);
                //   * any subsequent transition / progress event flips
                //     back to "running" — that's how the Resume button
                //     gets the banner to disappear after re-emitting an
                //     upstream ``*.completed`` event on top of an
                //     existing ``task.failed`` marker. We never regress
                //     out of "completed" though, so a stale child
                //     ``codetour.failed`` on a successful generation
                //     can't downgrade the status.
                if (event.type === "generation.completed") {
                    state.streams[streamId].info.status = "completed";
                } else if (event.type === "task.stopped") {
                    state.streams[streamId].info.status = "stopped";
                } else if (event.type === "task.resumed") {
                    // Explicit resume — clear the prior stopped/failed
                    // marker. Subsequent events flow through the running
                    // branch normally.
                    state.streams[streamId].info.status = "running";
                } else if (
                    event.type === "step.failed" ||
                    event.type === "task.failed" ||
                    event.type === "generation.failed"
                ) {
                    state.streams[streamId].info.status = "failed";
                } else if (
                    state.streams[streamId].info.status !== "completed" &&
                    state.streams[streamId].info.status !== "stopped" &&
                    state.streams[streamId].info.status !== "failed"
                ) {
                    // Trailing in-flight events (page.failed, page.written,
                    // ...) that arrive AFTER a terminal stop/failure must
                    // not silently demote the run back to "running" — that
                    // hides the Resume / Retry banner. Only a fresh
                    // ``task.resumed`` (above) can clear those flags.
                    state.streams[streamId].info.status = "running";
                }

                // Extract optional meta from generation.requested.
                if (event.type === "generation.requested") {
                    const data = (event.data || {}) as Record<string, unknown>;
                    state.streams[streamId].info.name =
                        (data.name as string) || state.streams[streamId].info.name;
                    state.streams[streamId].info.description =
                        (data.description as string) ||
                        state.streams[streamId].info.description;
                    state.streams[streamId].info.repo_id =
                        (data.repo_id as string) || state.streams[streamId].info.repo_id;
                }
            }
        },

        // Batched event push — invoked by the SSE saga every ~100ms with all
        // events accumulated in the window. Single Redux dispatch + single
        // re-render storm instead of one per SSE message. Critical for
        // generations that emit thousands of events (chunk.created etc).
        streamEventsBatchReceived: (
            state,
            action: PayloadAction<{ streamId: string; events: StreamEvent[] }>,
        ) => {
            const { streamId, events } = action.payload;
            const stream = state.streams[streamId];
            if (!stream || events.length === 0) return;

            const seenIds = new Set<string>();
            for (const e of stream.events) {
                if (e.id) seenIds.add(e.id);
            }

            for (const event of events) {
                if (event.id && seenIds.has(event.id)) continue;
                if (event.id) seenIds.add(event.id);
                stream.events.push(event);
                stream.info.event_count += 1;
                stream.info.last_event_id = event.id;

                if (
                    stream.traceId === null &&
                    typeof event.trace_id === "string" &&
                    event.trace_id.length > 0
                ) {
                    stream.traceId = event.trace_id;
                }

                // Mirror the per-event reducer above: newest event wins
                // so a Resume's upstream ``*.completed`` re-emit clears
                // the previous ``task.failed`` marker.
                if (event.type === "generation.completed") {
                    stream.info.status = "completed";
                } else if (event.type === "task.stopped") {
                    stream.info.status = "stopped";
                } else if (event.type === "task.resumed") {
                    stream.info.status = "running";
                } else if (
                    event.type === "step.failed" ||
                    event.type === "task.failed" ||
                    event.type === "generation.failed"
                ) {
                    stream.info.status = "failed";
                } else if (
                    stream.info.status !== "completed" &&
                    stream.info.status !== "stopped" &&
                    stream.info.status !== "failed"
                ) {
                    stream.info.status = "running";
                }

                if (event.type === "generation.requested") {
                    const data = (event.data || {}) as Record<string, unknown>;
                    stream.info.name =
                        (data.name as string) || stream.info.name;
                    stream.info.description =
                        (data.description as string) || stream.info.description;
                    stream.info.repo_id =
                        (data.repo_id as string) || stream.info.repo_id;
                }
            }

            stream.lastEventTs = Date.now();
            stream.sseStatus = "connected";
        },

        // Load historical events
        loadStreamEvents: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].error = null;
            }
        },
        loadStreamEventsSuccess: (
            state,
            action: PayloadAction<{ streamId: string; events: StreamEvent[] }>,
        ) => {
            const { streamId, events } = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].events = events;
                state.streams[streamId].info.event_count = events.length;
                if (events.length > 0) {
                    state.streams[streamId].info.last_event_id =
                        events[events.length - 1].id;
                }

                // Hydrate traceId from historical events when reloading the
                // detail view. Use the FIRST event that carries one so the
                // value matches what the gateway stamped at task creation.
                if (state.streams[streamId].traceId === null) {
                    const firstWithTrace = events.find(
                        (e) =>
                            typeof e.trace_id === "string" && e.trace_id.length > 0,
                    );
                    if (firstWithTrace?.trace_id) {
                        state.streams[streamId].traceId = firstWithTrace.trace_id;
                    }
                }

                // Derive meta/status from historical events (no extra API calls).
                const requested = events.find((e) => e.type === "generation.requested");
                if (requested) {
                    const data = (requested.data || {}) as Record<string, unknown>;
                    state.streams[streamId].info.name =
                        (data.name as string) || state.streams[streamId].info.name;
                    state.streams[streamId].info.description =
                        (data.description as string) ||
                        state.streams[streamId].info.description;
                    state.streams[streamId].info.repo_id =
                        (data.repo_id as string) || state.streams[streamId].info.repo_id;
                }

                // Initial load (history fetch). ``events`` arrives
                // oldest-first, so the LAST entry is the most recent.
                // Match the per-event derivation: newest wins so a
                // Resume re-emit doesn't get masked by an older
                // ``task.failed`` still sitting in the history.
                const newestEvent = events[events.length - 1];
                const newestType = newestEvent?.type;
                if (newestType === "generation.completed") {
                    state.streams[streamId].info.status = "completed";
                } else if (newestType === "task.stopped") {
                    state.streams[streamId].info.status = "stopped";
                } else if (
                    newestType === "step.failed" ||
                    newestType === "task.failed" ||
                    newestType === "generation.failed"
                ) {
                    state.streams[streamId].info.status = "failed";
                } else if (newestType) {
                    state.streams[streamId].info.status = "running";
                } else {
                    state.streams[streamId].info.status = "pending";
                }
            }
        },
        loadStreamEventsFailure: (
            state,
            action: PayloadAction<{ streamId: string; error: string }>,
        ) => {
            const { streamId, error } = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].error = error;
            }
        },

        // Heartbeat / ping that is not part of the historical event log but
        // proves the EventSource is still alive. Used to refresh staleness.
        streamPing: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].lastEventTs = Date.now();
                state.streams[streamId].sseStatus = "connected";
            }
        },

        // Disconnect from stream
        disconnectFromStream: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            if (state.streams[streamId]) {
                state.streams[streamId].isConnected = false;
                state.streams[streamId].sseStatus = "disconnected";
            }
            if (state.activeStreamId === streamId) {
                state.activeStreamId = null;
            }
        },

        // Clear stream data
        clearStream: (state, action: PayloadAction<string>) => {
            const streamId = action.payload;
            delete state.streams[streamId];
            if (state.activeStreamId === streamId) {
                state.activeStreamId = null;
            }
        },
    },
});

export const {
    fetchStreamsList,
    fetchStreamsListSuccess,
    fetchStreamsListFailure,
    connectToStream,
    streamConnecting,
    streamConnected,
    streamDisconnected,
    streamStale,
    streamPing,
    streamError,
    streamEventReceived,
    streamEventsBatchReceived,
    loadStreamEvents,
    loadStreamEventsSuccess,
    loadStreamEventsFailure,
    disconnectFromStream,
    clearStream,
} = streamsSlice.actions;

export default streamsSlice.reducer;
