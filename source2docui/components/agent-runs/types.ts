/** Mirrors ``AgentRunSummary`` in ``core/gateway/app/routes/generations/dto.py``.
 *
 * The fields are intentionally optional / nullable on the wire — older
 * generations from before migration 20 won't have rows at all, and rows
 * for failed runs may have null token / cost columns.
 */
export interface AgentRunSummary {
    id: number;
    generation_id: string;
    page_id: string | null;
    section_id: string | null;
    agent_name: string;
    attempt: number;
    started_at: string;
    finished_at: string | null;
    duration_ms: number | null;
    success: boolean;
    error_type: string | null;
    error_message: string | null;
    request_count: number | null;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    cost_usd: number | null;
    trace_id: string | null;
}

export interface AgentRunsResponse {
    generation_id: string;
    items: AgentRunSummary[];
    limit: number;
    offset: number;
}

/** Mirrors ``AgentRunDetail`` — the summary plus the full conversation. */
export interface AgentRunDetail extends AgentRunSummary {
    /** Pydantic-AI ``ModelMessage`` list dump. Shape varies by SDK version. */
    messages: unknown;
    output: unknown;
}
