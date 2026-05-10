-- Persistent Pydantic-AI agent run history.
--
-- Every LLM round-trip routed through ``source2doc.agents.runner.run_agent``
-- (planner / subplanner / writer / critic / diagrammer) writes one row
-- here so we can replay the conversation later and figure out where a
-- model went wrong. ``messages`` is the JSON dump of the full
-- ``ModelMessage`` list (system prompt + user prompt + tool calls + tool
-- results + final output), produced via
-- ``ModelMessagesTypeAdapter.dump_python(..., mode='json')``.
--
-- The table is **append-only** — we never UPDATE an existing run and we
-- never reuse the primary key. Failures are recorded too (with
-- ``success = false`` and a populated ``error_type`` / ``error_message``)
-- so a retry shows up as a separate row with ``attempt = N+1``.
--
-- Columns intentionally mirror generation_metrics where they overlap so a
-- future join doesn't need translation:
--   * ``input_tokens``  ← maps to generation_metrics.prompt_tokens
--   * ``output_tokens`` ← maps to generation_metrics.completion_tokens

CREATE TABLE IF NOT EXISTS agent_runs (
    id              BIGSERIAL PRIMARY KEY,
    generation_id   UUID NOT NULL,
    page_id         TEXT,                 -- nullable: planner/subplanner have no page
    section_id      TEXT,                 -- nullable: only subplanner sets this
    agent_name      TEXT NOT NULL,        -- planner | subplanner | writer | critic | diagrammer
    attempt         INTEGER NOT NULL DEFAULT 1,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    success         BOOLEAN NOT NULL DEFAULT FALSE,
    error_type      TEXT,
    error_message   TEXT,
    request_count   INTEGER,              -- LLM round-trips
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER,
    cost_usd        NUMERIC(12,6),
    messages        JSONB NOT NULL,       -- full ModelMessage list dump
    output          JSONB,                -- structured output (or null on failure)
    trace_id        TEXT
);

CREATE INDEX IF NOT EXISTS agent_runs_generation_id_idx
    ON agent_runs(generation_id);
CREATE INDEX IF NOT EXISTS agent_runs_agent_name_idx
    ON agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS agent_runs_started_at_idx
    ON agent_runs(started_at DESC);

COMMENT ON TABLE agent_runs IS
    'Append-only history of every Pydantic-AI agent.run() invocation in a docgen pipeline.';
COMMENT ON COLUMN agent_runs.messages IS
    'Full ModelMessage list dumped via ModelMessagesTypeAdapter (mode=json).';
COMMENT ON COLUMN agent_runs.output IS
    'Structured agent output (the .output field of the AgentRunResult); null when the run failed.';
COMMENT ON COLUMN agent_runs.attempt IS
    'Logical retry attempt number scoped to (generation_id, page_id, section_id, agent_name).';

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO docgen;
