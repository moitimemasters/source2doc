// Plain-TS SSE wrapper with exponential-backoff reconnect.
//
// Replaces ad-hoc `new EventSource(...)` usage across the UI. The browser's
// built-in EventSource reconnect is opaque (no observable state, ~3s default
// retry, no jitter), and several call sites previously short-circuited it by
// closing the source on first error. This helper:
//
//   - Surfaces a `connecting` / `connected` lifecycle via `onStateChange`.
//   - Reconnects on error with exponential backoff: 1, 2, 4, 8, 16, 30s
//     (capped). ±20 % jitter avoids thundering-herd when a worker restart
//     drops many tabs at once.
//   - Resets the attempt counter once a real `message` (or named) event lands
//     so a reconnect that succeeds doesn't keep escalating delay.
//   - Cancels pending timers on `close()` or `signal.abort()` so unmount is
//     race-free.
//
// Intentionally has zero dependencies on Redux / React — usable from sagas,
// plain modules, and hooks alike. Watchdog-style staleness detection (e.g.
// downgrade `connected` -> `disconnected` after 15 s of silence) is the
// caller's responsibility and is unaffected by this module.

export type SseStatus = "connecting" | "connected" | "disconnected";

export interface CreateSSEOptions {
    /** Default-message handler (`source.onmessage`). */
    onMessage?: (event: MessageEvent) => void;
    /**
     * Map of named SSE event types to their listeners. Equivalent to calling
     * `source.addEventListener(type, listener)` for each entry. Listeners are
     * re-attached on every reconnect, so callers don't need to re-subscribe.
     */
    onEvent?: Record<string, (event: MessageEvent) => void>;
    /** Lifecycle callback. Fires on every transition. */
    onStateChange?: (status: SseStatus) => void;
    /** Optional abort signal — equivalent to calling `close()`. */
    signal?: AbortSignal;
    /**
     * Override for `setTimeout` / `clearTimeout`. Exists purely so unit tests
     * can drive the backoff schedule with fake timers; production callers
     * should leave this unset.
     */
    timers?: {
        setTimeout: (fn: () => void, ms: number) => unknown;
        clearTimeout: (handle: unknown) => void;
    };
    /**
     * Override the EventSource constructor. Test-only, same rationale as
     * `timers` — lets unit tests inject a fake.
     */
    eventSourceFactory?: (url: string) => EventSource;
}

export interface SSEHandle {
    /** Tear down the active EventSource and cancel any pending reconnect. */
    close: () => void;
}

// 1, 2, 4, 8, 16, 30, 30, 30, ... seconds (capped). ±20% jitter applied on top.
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30_000;
const JITTER = 0.2;

function computeBackoffMs(
    attempt: number,
    rng: () => number = Math.random,
): number {
    // attempt=0 → 1s, 1 → 2s, 2 → 4s, 3 → 8s, 4 → 16s, 5+ → 30s (cap)
    const exp = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
    // Symmetric ±20% jitter: rng()*2-1 ∈ [-1, 1).
    const jitterFactor = 1 + (rng() * 2 - 1) * JITTER;
    return Math.max(0, Math.round(exp * jitterFactor));
}

/**
 * Open an EventSource with auto-reconnect and observable state.
 *
 * The returned handle's `close()` is idempotent. Calling it after the signal
 * has aborted is a no-op.
 */
export function createSSE(
    url: string,
    opts: CreateSSEOptions = {},
): SSEHandle {
    const {
        onMessage,
        onEvent,
        onStateChange,
        signal,
        timers,
        eventSourceFactory,
    } = opts;
    const setTimeoutFn = timers?.setTimeout ?? (globalThis.setTimeout as any);
    const clearTimeoutFn =
        timers?.clearTimeout ?? (globalThis.clearTimeout as any);
    const makeES =
        eventSourceFactory ?? ((u: string) => new EventSource(u));

    let attempt = 0;
    let current: EventSource | null = null;
    let pendingTimer: unknown = null;
    let closed = false;
    let lastStatus: SseStatus | null = null;

    const emitState = (status: SseStatus) => {
        if (lastStatus === status) return;
        lastStatus = status;
        try {
            onStateChange?.(status);
        } catch {
            // Listener errors must not break reconnect.
        }
    };

    const teardownCurrent = () => {
        if (!current) return;
        try {
            current.onopen = null;
            current.onmessage = null;
            current.onerror = null;
        } catch {
            /* defensive */
        }
        try {
            current.close();
        } catch {
            /* defensive */
        }
        current = null;
    };

    const cancelPending = () => {
        if (pendingTimer !== null) {
            clearTimeoutFn(pendingTimer);
            pendingTimer = null;
        }
    };

    const scheduleReconnect = () => {
        if (closed) return;
        emitState("connecting");
        const delay = computeBackoffMs(attempt);
        attempt += 1;
        pendingTimer = setTimeoutFn(() => {
            pendingTimer = null;
            connect();
        }, delay);
    };

    const connect = () => {
        if (closed) return;
        teardownCurrent();
        emitState("connecting");

        let es: EventSource;
        try {
            es = makeES(url);
        } catch {
            // Constructor itself failed (invalid URL etc.) — back off and
            // retry on the same schedule rather than crashing the caller.
            scheduleReconnect();
            return;
        }
        current = es;

        es.onopen = () => {
            emitState("connected");
        };

        es.onmessage = (event) => {
            // Any event on the wire proves the connection is healthy.
            attempt = 0;
            emitState("connected");
            onMessage?.(event);
        };

        if (onEvent) {
            for (const [type, listener] of Object.entries(onEvent)) {
                const wrapped = (event: MessageEvent) => {
                    attempt = 0;
                    emitState("connected");
                    listener(event);
                };
                es.addEventListener(type, wrapped as EventListener);
            }
        }

        es.onerror = () => {
            // EventSource transitions to CLOSED only for terminal failures;
            // for transient drops it would reconnect on its own with no
            // observable state. We unconditionally tear it down and run our
            // own backoff so the lifecycle is uniform.
            teardownCurrent();
            scheduleReconnect();
        };
    };

    const close = () => {
        if (closed) return;
        closed = true;
        cancelPending();
        teardownCurrent();
        emitState("disconnected");
    };

    if (signal) {
        if (signal.aborted) {
            // Mirror EventSource semantics: still emit a disconnect so callers
            // observing the lifecycle see the final state.
            closed = true;
            emitState("disconnected");
            return { close };
        }
        signal.addEventListener("abort", close, { once: true });
    }

    // Kick off the first attempt synchronously so the first connect happens
    // immediately rather than after the first backoff window.
    connect();

    return { close };
}

// Exported only for unit testing.
export const __test = { computeBackoffMs };
