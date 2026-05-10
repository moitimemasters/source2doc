-- Capture wall-clock duration for each agent step (planner / writer / critic
-- / etc.) so the metrics dashboard can show p50/p95 latency over time.
--
-- Closes ТЗ items МНТ-06, МТР-01, МТР-02 (B3.4). Pairs with the existing
-- token+cost columns from migration 10 — same row, just additional
-- timing fields. ``duration_ms`` is denormalized for cheap aggregation
-- (saves a (completed - started) cast in every dashboard query).
--
-- Pre-prod / docker-compose / disposable data — no downgrade.

ALTER TABLE generation_metrics
    ADD COLUMN IF NOT EXISTS step_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS step_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS duration_ms BIGINT;

CREATE INDEX IF NOT EXISTS idx_generation_metrics_step_completed_at
    ON generation_metrics(step_completed_at);

CREATE INDEX IF NOT EXISTS idx_generation_metrics_model
    ON generation_metrics(model);

CREATE INDEX IF NOT EXISTS idx_generation_metrics_step
    ON generation_metrics(step);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO docgen;
