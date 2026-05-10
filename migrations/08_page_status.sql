-- Track per-page generation status so the UI can surface pages that the
-- writer/critic failed on instead of rendering empty placeholder content.
-- A page is `completed` once it survives review; `failed` if the agent
-- exhausted retries (e.g. tool-retry max, model-behavior, usage limit).

ALTER TABLE documentation_pages
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS error TEXT;

CREATE INDEX IF NOT EXISTS idx_pages_status ON documentation_pages(status);
