-- 06_add_codetour_status.sql
-- Code Tour lifecycle status (pending → running → completed | failed | cancelled).
-- Stream events are the source of truth for progress within a tour, but the
-- terminal status and summary fields live in Postgres so the UI can list
-- tours without scanning Redis.

ALTER TABLE codetours
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS request_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_codetours_status ON codetours(status);
CREATE INDEX IF NOT EXISTS idx_codetours_generation_status
    ON codetours(generation_id, status);

GRANT ALL PRIVILEGES ON codetours TO docgen;
