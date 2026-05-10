-- Persist token usage and cost per generation/step so the API and UI can
-- show totals per generation_id. Closes ТЗ items LLM-03, LLM-04, МТР-03
-- (B3.1).
--
-- Logfire spans already capture token usage in the trace, but we also
-- aggregate them in our own DB so the wiki UI can surface a "Total
-- tokens / cost" badge without depending on Logfire's API.
--
-- One row per agent run (planner/writer/critic/etc.). Aggregates are
-- computed via SUM() in the gateway service layer.

CREATE TABLE IF NOT EXISTS generation_metrics (
    id BIGSERIAL PRIMARY KEY,
    generation_id UUID NOT NULL,
    step TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER GENERATED ALWAYS AS (prompt_tokens + completion_tokens) STORED,
    cost_usd NUMERIC(10, 6),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_generation_metrics_generation_id
    ON generation_metrics(generation_id);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO docgen;
