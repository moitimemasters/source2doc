-- Add ``trace_id`` + ``extras`` columns to ``generation_metrics`` so the
-- B13.4 admin diagnostic endpoint (СПР-04) can answer
-- ``GET /api/v1/admin/trace/{trace_id}`` by joining metrics → Redis
-- streams via the trace correlation token bound by B3.3.
--
-- Pre-prod, docker-compose, disposable data — column-additive only,
-- safe on a freshly-migrated DB and on top of the legacy columns from
-- migrations 10 + 14.

ALTER TABLE generation_metrics
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS extras JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_generation_metrics_trace_id
    ON generation_metrics(trace_id)
    WHERE trace_id IS NOT NULL;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO docgen;
