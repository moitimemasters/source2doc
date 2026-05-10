-- Append-only history for documentation pages.
--
-- Every successful generation that writes a row into ``documentation_pages``
-- also writes one row here as a snapshot. The wiki UI uses this to render
-- a "Versions" dropdown next to the page metadata strip — readers can
-- pick a past commit/run and re-render the body that was produced for it.
--
-- The current ``documentation_pages`` row stays canonical for "latest"
-- reads (``GET /pages/{id}`` is unchanged); ``page_versions`` is only
-- consulted when an explicit ``version_generation_id`` is requested.
--
-- Closes ТЗ ГЕН-08 (B11.2).
--
-- Pre-prod / docker-compose / disposable data — no downgrade.

CREATE TABLE IF NOT EXISTS page_versions (
    id BIGSERIAL PRIMARY KEY,
    page_id TEXT NOT NULL,
    generation_id UUID NOT NULL,
    repository_id UUID,
    commit_sha TEXT,
    body JSONB NOT NULL,
    body_markdown TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (page_id, generation_id)
);

CREATE INDEX IF NOT EXISTS idx_page_versions_lookup
    ON page_versions(page_id, created_at DESC);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO docgen;
