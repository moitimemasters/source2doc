import { createSSE } from "@/lib/sse/createSSE";

export type StepKind = "entry" | "transition" | "leaf" | "gotcha";

export interface StepHighlight {
    line: number;
    note: string;
}

export interface CommitRef {
    sha: string;
    short_sha?: string | null;
    author?: string | null;
    date?: string | null;
    message?: string | null;
}

export interface AuthorshipInfo {
    primary_author: string;
    primary_share?: number;
    last_modified_at?: string | null;
    last_commit?: string | null;
    contributors?: string[];
}

export interface CodetourStep {
    title: string;
    description: string;
    file: string;
    line: number;
    end_line?: number;
    code?: string;
    pattern?: string;
    kind?: StepKind;
    key_idea?: string | null;
    highlights?: StepHighlight[];
    connects_to?: number[];
    commits?: CommitRef[];
    authorship?: AuthorshipInfo | null;
}

export interface CodetourDetail {
    tour_id: string;
    generation_id: string;
    title: string;
    description: string;
    steps: CodetourStep[];
    created_at: string;
    metadata: Record<string, any>;
    status?: string;
    error_message?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
}

export interface CodetourInfo {
    tour_id: string;
    generation_id: string;
    title: string;
    description: string;
    created_at: string;
    status?: string;
}

export interface LLMConfigInput {
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
    temperature?: number;
    max_tokens?: number;
}

export interface EmbeddingsConfigInput {
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
    dimensions?: number;
    batch_size?: number;
    concurrency?: number;
}

export interface QdrantConfigInput {
    url: string;
    collection?: string;
    api_key?: string | null;
}

export type TourMode = "overview" | "deep-dive" | "gotchas";

export interface CodetourRequest {
    query: string;
    generation_id: string;
    max_steps?: number;
    mode?: TourMode;
    repo_id?: string | null;
}

export interface FollowupRequest {
    step_index: number;
    question: string;
    max_new_steps?: number;
}

export interface FollowupResponse {
    tour_id: string;
    request_id: string;
    status: string;
    message: string;
}

export interface CodetourResponse {
    tour_id: string;
    generation_id: string;
    status: string;
    message: string;
}

export interface CodetourListResponse {
    tours: CodetourInfo[];
}

async function createCodetour(request: CodetourRequest): Promise<CodetourResponse> {
    const response = await fetch("/api/gateway/codetours", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || error.error || "Failed to create codetour");
    }

    return response.json();
}

async function getTour(tourId: string): Promise<CodetourDetail> {
    const response = await fetch(`/api/gateway/codetours/${tourId}`);

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || "Failed to get tour");
    }

    return response.json();
}

async function listToursByGeneration(
    generationId: string,
): Promise<CodetourInfo[]> {
    const response = await fetch(
        `/api/gateway/codetours/generation/${generationId}`,
    );

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || "Failed to list tours");
    }

    const data: CodetourListResponse = await response.json();
    return data.tours;
}

async function listAllTours(
    limit: number = 100,
    offset: number = 0,
): Promise<CodetourInfo[]> {
    const response = await fetch(
        `/api/gateway/codetours?limit=${limit}&offset=${offset}`,
    );

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || "Failed to list tours");
    }

    const data: CodetourListResponse = await response.json();
    return data.tours;
}

async function requestFollowup(
    tourId: string,
    request: FollowupRequest,
): Promise<FollowupResponse> {
    const response = await fetch(`/api/gateway/codetours/${tourId}/followup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
    });
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(
            error.detail || error.error || "Failed to request follow-up",
        );
    }
    return response.json();
}

async function cancelTour(tourId: string): Promise<void> {
    const response = await fetch(`/api/gateway/codetours/${tourId}/cancel`, {
        method: "POST",
    });
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || "Failed to cancel tour");
    }
}

const TERMINAL_TOUR_EVENTS = new Set([
    "codetour.completed",
    "codetour.failed",
    "codetour.cancelled",
]);

type TourEventType =
    | "codetour.started"
    | "codetour.step_added"
    | "codetour.step_rejected"
    | "codetour.step_line_drift"
    | "codetour.completed"
    | "codetour.failed"
    | "codetour.cancelled"
    | "codetour.followup_requested"
    | "codetour.followup_started"
    | "codetour.followup_step_added"
    | "codetour.followup_step_rejected"
    | "codetour.followup_completed"
    | "codetour.followup_failed";

export type CodetourSseStatus = "connecting" | "connected" | "disconnected";

export interface CodetourSseStateUpdate {
    status: CodetourSseStatus;
    /** Epoch ms of the most recent event/ping/open marker, or null. */
    lastEventTs: number | null;
}

export interface SubscribeToTourStreamOptions {
    onEvent: (type: TourEventType, data: any) => void;
    /** Optional listener that receives SSE lifecycle updates. */
    onSseState?: (state: CodetourSseStateUpdate) => void;
}

// All named SSE event types the gateway emits on the codetour stream.
const TOUR_EVENT_TYPES: TourEventType[] = [
    "codetour.started",
    "codetour.step_added",
    "codetour.step_rejected",
    "codetour.step_line_drift",
    "codetour.completed",
    "codetour.failed",
    "codetour.cancelled",
    "codetour.followup_requested",
    "codetour.followup_started",
    "codetour.followup_step_added",
    "codetour.followup_step_rejected",
    "codetour.followup_completed",
    "codetour.followup_failed",
];

function subscribeToTourStream(
    tourId: string,
    onEventOrOptions:
        | ((type: TourEventType, data: any) => void)
        | SubscribeToTourStreamOptions,
): () => void {
    const opts: SubscribeToTourStreamOptions =
        typeof onEventOrOptions === "function"
            ? { onEvent: onEventOrOptions }
            : onEventOrOptions;
    const { onEvent, onSseState } = opts;

    let lastEventTs: number | null = null;
    let terminated = false;
    // Captured by closures below; populated immediately after createSSE
    // returns. Indirected through this object so the named-event handlers
    // (which fire only after `createSSE` has returned) can call `close()`
    // without TypeScript complaining about used-before-assigned.
    const handleRef: { close: () => void } = { close: () => {} };

    const emitState = (status: CodetourSseStatus) => {
        onSseState?.({ status, lastEventTs });
    };

    const touch = () => {
        lastEventTs = Date.now();
    };

    const handlers: Record<string, (e: MessageEvent) => void> = {
        // Keepalives — refresh the freshness clock so the watchdog in
        // TourLiveView does not flip to `disconnected`.
        ping: () => {
            touch();
            // Keep the indicator on green explicitly: createSSE has already
            // surfaced "connected" via state change, but we want lastEventTs
            // to flow into onSseState too.
            emitState("connected");
        },
    };
    for (const type of TOUR_EVENT_TYPES) {
        handlers[type] = (e: MessageEvent) => {
            let parsed: any = e.data;
            try {
                parsed = JSON.parse(e.data);
            } catch {
                // leave as raw string
            }
            touch();
            emitState("connected");
            onEvent(type, parsed);
            if (TERMINAL_TOUR_EVENTS.has(type)) {
                // Tour reached a terminal state — stop reconnecting.
                terminated = true;
                handleRef.close();
            }
        };
    }

    emitState("connecting");

    const sse = createSSE(`/api/gateway/codetours/${tourId}/stream`, {
        onEvent: handlers,
        onStateChange: (status) => {
            // Suppress `connected` chatter — the named-event handlers already
            // propagate it with an updated lastEventTs. We DO want to surface
            // `connecting` (mid-reconnect) and `disconnected` (terminal).
            if (status === "connecting") {
                emitState("connecting");
            } else if (status === "disconnected") {
                emitState("disconnected");
            }
        },
    });
    handleRef.close = sse.close;

    return () => {
        if (!terminated) {
            terminated = true;
            sse.close();
        }
    };
}

async function pollTourCompletion(
    tourId: string,
    onProgress?: (attempt: number) => void,
    maxAttempts: number = 30,
    intervalMs: number = 2000,
): Promise<CodetourDetail> {
    for (let i = 0; i < maxAttempts; i++) {
        if (onProgress) {
            onProgress(i + 1);
        }

        try {
            const tour = await getTour(tourId);
            if (
                tour.status === "completed" ||
                tour.status === "failed" ||
                tour.status === "cancelled"
            ) {
                return tour;
            }
        } catch {
            // tour not yet visible; retry
        }
        if (i < maxAttempts - 1) {
            await new Promise((resolve) => setTimeout(resolve, intervalMs));
        }
    }

    throw new Error("Tour generation timeout");
}

export const codetourAPI = {
    createCodetour,
    getTour,
    listToursByGeneration,
    listAllTours,
    cancelTour,
    requestFollowup,
    subscribeToTourStream,
    pollTourCompletion,
};
