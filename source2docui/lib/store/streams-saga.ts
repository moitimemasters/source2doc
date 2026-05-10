import {
    call,
    put,
    take,
    fork,
    cancel,
    delay,
} from "redux-saga/effects";
import { eventChannel, EventChannel, Task } from "redux-saga";
import { PayloadAction } from "@reduxjs/toolkit";
import type { SagaIterator } from "redux-saga";
import {
    connectToStream,
    disconnectFromStream,
    streamConnecting,
    streamConnected,
    streamDisconnected,
    streamStale,
    streamPing,
    streamError,
    streamEventReceived,
    streamEventsBatchReceived,
    fetchStreamsList,
    fetchStreamsListSuccess,
    fetchStreamsListFailure,
    loadStreamEvents,
    loadStreamEventsSuccess,
    loadStreamEventsFailure,
} from "./streams-slice";
import { StreamEvent, StreamListResponse } from "@/lib/gateway/types";
import { createSSE } from "@/lib/sse/createSSE";

// Window after which a connected SSE channel is considered stale if no event
// or ping has arrived. Must exceed the gateway's keepalive cadence.
const SSE_STALE_TIMEOUT_MS = 15_000;
// Watchdog tick frequency.
const SSE_WATCHDOG_INTERVAL_MS = 1_000;
// SSE event batching window: collect events for this many ms then dispatch a
// single ``streamEventsBatchReceived`` action. Trades a tiny bit of latency
// for an order-of-magnitude drop in React re-renders during heavy phases.
const SSE_BATCH_FLUSH_MS = 100;

// Channel payload — either a real stream event, a ping/open marker, or a
// reconnect notification surfaced from the underlying SSE helper.
type ChannelMsg =
    | { kind: "open" }
    | { kind: "ping" }
    | { kind: "event"; event: StreamEvent }
    | { kind: "connecting" };

// API calls
async function fetchStreamsListAPI(): Promise<StreamListResponse> {
    const response = await fetch("/api/gateway/streams");
    if (!response.ok) {
        throw new Error(`Failed to fetch streams: ${response.statusText}`);
    }
    return response.json();
}

async function fetchStreamEventsAPI(streamId: string): Promise<StreamEvent[]> {
    const response = await fetch(`/api/gateway/streams/${streamId}/events`);
    if (!response.ok) {
        throw new Error(`Failed to fetch events: ${response.statusText}`);
    }
    // Gateway returns ``list[StreamEvent]`` directly (response_model on the
    // FastAPI route). The legacy ``data.events`` access here silently
    // resolved to ``undefined`` on every fetch and ``|| []`` masked it,
    // so historical events never landed in the slice — status was driven
    // entirely by the slow SSE replay, which kept it at "running" for
    // long-event streams until the trailing terminal event finally
    // streamed in. Accept either shape so a future gateway change to
    // ``{events: [...]}`` still works without another UI rebuild.
    const data = await response.json();
    if (Array.isArray(data)) return data;
    return data?.events || [];
}

// Create SSE event channel.
//
// Backed by `createSSE`, which owns the EventSource lifecycle and reconnects
// with exponential backoff (1/2/4/8/16/30s ±20% jitter). The channel stays
// open across reconnects — we forward `connecting` markers so the UI dot
// flips back to yellow during retry windows. The watchdog saga still
// downgrades stale `connected` states to `disconnected` after 15s of silence.
function createStreamChannel(streamId: string): EventChannel<ChannelMsg> {
    return eventChannel((emit) => {
        const handle = createSSE(`/api/gateway/streams/${streamId}/stream`, {
            onMessage: (event) => {
                try {
                    const data = JSON.parse(event.data);
                    emit({ kind: "event", event: data });
                } catch (error) {
                    console.error("Failed to parse SSE event:", error);
                }
            },
            onEvent: {
                // Gateway emits keepalives as a named `ping` event. They have
                // no payload we care about — just refresh the freshness clock.
                ping: () => {
                    emit({ kind: "ping" });
                },
            },
            onStateChange: (status) => {
                if (status === "connected") {
                    emit({ kind: "open" });
                } else if (status === "connecting") {
                    emit({ kind: "connecting" });
                }
                // `disconnected` only fires from explicit close(); the saga's
                // finally block will dispatch streamDisconnected itself.
            },
        });

        return () => {
            handle.close();
        };
    });
}

// Saga: Fetch streams list
function* fetchStreamsListSaga() {
    try {
        const data: StreamListResponse = yield call(fetchStreamsListAPI);
        yield put(fetchStreamsListSuccess(data.streams));
    } catch (error) {
        const message =
            error instanceof Error ? error.message : "Unknown error";
        yield put(fetchStreamsListFailure(message));
    }
}

// Saga: Load stream events
function* loadStreamEventsSaga(action: PayloadAction<string>) {
    const streamId = action.payload;
    try {
        const events: StreamEvent[] = yield call(
            fetchStreamEventsAPI,
            streamId,
        );
        yield put(loadStreamEventsSuccess({ streamId, events }));
    } catch (error) {
        const message =
            error instanceof Error ? error.message : "Unknown error";
        yield put(loadStreamEventsFailure({ streamId, error: message }));
    }
}

// Side-channel between the monitor loop and its watchdog. Avoids round-
// tripping through the store just to know whether to downgrade status.
const lastSeenByStream = new Map<string, number>();

// Watchdog: every second, downgrade `connected` -> `disconnected` if the
// last event/ping is older than the staleness threshold. The reducer keeps
// `connecting` and `disconnected` immune to this transition, so emitting the
// action unconditionally is safe.
function* sseWatchdogSaga(streamId: string): SagaIterator {
    while (true) {
        yield delay(SSE_WATCHDOG_INTERVAL_MS);
        const lastSeen = lastSeenByStream.get(streamId) ?? Date.now();
        if (Date.now() - lastSeen > SSE_STALE_TIMEOUT_MS) {
            yield put(streamStale(streamId));
        }
    }
}

// Saga: Monitor stream via SSE
function* monitorStreamSaga(action: PayloadAction<string>): SagaIterator {
    const streamId = action.payload;
    let channel: EventChannel<ChannelMsg> | null = null;

    try {
        // First, load historical events
        yield put(loadStreamEvents(streamId));

        // Wait for historical events to load
        yield delay(500);

        // Surface the connecting state to the indicator before the
        // EventSource opens.
        yield put(streamConnecting(streamId));

        // Create SSE channel
        channel = (yield call(
            createStreamChannel,
            streamId,
        )) as EventChannel<ChannelMsg>;

        const watchdog = (yield fork(sseWatchdogSaga, streamId)) as Task;

        // Buffer per-stream events so the SSE saga dispatches one batched
        // Redux action per ~100ms tick instead of one per SSE message.
        // Critical when the gateway emits thousands of events in a few
        // seconds (chunk.created, file.ingested) — single dispatch keeps
        // React from re-rendering 100s of times per second.
        const buffer: StreamEvent[] = [];
        let flushScheduled = false;

        function* scheduleFlush(): SagaIterator {
            if (flushScheduled) return;
            flushScheduled = true;
            yield delay(SSE_BATCH_FLUSH_MS);
            if (buffer.length > 0) {
                const drained = buffer.splice(0, buffer.length);
                yield put(
                    streamEventsBatchReceived({ streamId, events: drained }),
                );
            }
            flushScheduled = false;
        }

        try {
            // Listen for events / pings / open
            while (true) {
                const msg: ChannelMsg = (yield take(channel)) as ChannelMsg;
                if (msg.kind === "open") {
                    yield put(streamConnected(streamId));
                    lastSeenByStream.set(streamId, Date.now());
                } else if (msg.kind === "ping") {
                    yield put(streamPing(streamId));
                    lastSeenByStream.set(streamId, Date.now());
                } else if (msg.kind === "event") {
                    buffer.push(msg.event);
                    lastSeenByStream.set(streamId, Date.now());
                    yield fork(scheduleFlush);
                } else if (msg.kind === "connecting") {
                    // Helper is in a reconnect window — flip the indicator
                    // back to yellow. We deliberately do NOT touch
                    // `lastSeenByStream` so the watchdog can still escalate
                    // to `disconnected` if the retry storm runs long.
                    yield put(streamConnecting(streamId));
                }
            }
        } finally {
            yield cancel(watchdog);
            lastSeenByStream.delete(streamId);
        }
    } catch (error) {
        const message =
            error instanceof Error ? error.message : "Unknown error";
        yield put(streamError({ streamId, error: message }));
    } finally {
        if (channel) {
            channel.close();
        }
        yield put(streamDisconnected(streamId));
    }
}

// Saga: Handle stream connection
function* handleConnectToStreamSaga(
    action: PayloadAction<string>,
): SagaIterator {
    const monitorTask = (yield fork(monitorStreamSaga, action)) as Task;

    // Wait for disconnect action
    yield take(disconnectFromStream.type);

    // Cancel monitoring
    yield cancel(monitorTask);
}

// Root saga
export function* streamsSaga(): SagaIterator {
    // Track active connect tasks per stream so React StrictMode (which double-
    // fires effects in dev) and accidental double connects don't create two
    // SSE channels + two historical-events fetches for the same stream.
    const activeConnects = new Map<string, Task>();

    while (true) {
        const action: PayloadAction<string> = yield take([
            fetchStreamsList.type,
            loadStreamEvents.type,
            connectToStream.type,
            disconnectFromStream.type,
        ]);

        if (action.type === fetchStreamsList.type) {
            yield fork(fetchStreamsListSaga);
        } else if (action.type === loadStreamEvents.type) {
            yield fork(loadStreamEventsSaga, action);
        } else if (action.type === connectToStream.type) {
            const streamId = action.payload;
            const existing = activeConnects.get(streamId);
            if (existing && existing.isRunning()) continue;
            const task = (yield fork(handleConnectToStreamSaga, action)) as Task;
            activeConnects.set(streamId, task);
        } else if (action.type === disconnectFromStream.type) {
            activeConnects.delete(action.payload);
        }
    }
}
