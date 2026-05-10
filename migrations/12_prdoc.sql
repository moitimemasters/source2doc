-- PR microdoc summaries (closes ТЗ items ИНТ-02, ГЕН-06).
--
-- One row per /api/v1/prdoc generation. The Markdown summary is meant to
-- be posted directly as a PR comment; ``highlights`` and ``concerns`` are
-- structured arrays so a future renderer can lay them out as bullets.
--
-- generation_id is a UUID minted by the gateway, *independent* from the
-- documentation_bundles.generation_id namespace — a PR doc is not tied to
-- a specific bundle, even though the optional ``repo_id`` may be reused
-- to fetch RAG context from the repo's Qdrant collection.

CREATE TABLE IF NOT EXISTS prdoc_summaries (
    generation_id UUID PRIMARY KEY,
    repo_id UUID,
    base_sha TEXT,
    head_sha TEXT,
    title TEXT,
    summary TEXT NOT NULL DEFAULT '',
    highlights JSONB NOT NULL DEFAULT '[]'::jsonb,
    concerns JSONB NOT NULL DEFAULT '[]'::jsonb,
    files_summarised INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_prdoc_summaries_repo_id ON prdoc_summaries(repo_id);
CREATE INDEX IF NOT EXISTS idx_prdoc_summaries_status ON prdoc_summaries(status);
CREATE INDEX IF NOT EXISTS idx_prdoc_summaries_created_at ON prdoc_summaries(created_at);

COMMENT ON TABLE prdoc_summaries IS 'PR microdoc summaries generated from a diff snapshot';
COMMENT ON COLUMN prdoc_summaries.generation_id IS 'Unique identifier for the prdoc run';
COMMENT ON COLUMN prdoc_summaries.repo_id IS 'Optional reference to repositories.repo_id; enables RAG context';
COMMENT ON COLUMN prdoc_summaries.base_sha IS 'Optional base commit SHA, displayed in the rendered summary';
COMMENT ON COLUMN prdoc_summaries.head_sha IS 'Optional head commit SHA';
COMMENT ON COLUMN prdoc_summaries.summary IS 'Markdown summary suitable for posting as a PR comment';
COMMENT ON COLUMN prdoc_summaries.highlights IS 'Notable improvements (array of strings)';
COMMENT ON COLUMN prdoc_summaries.concerns IS 'Risks / concerns flagged by the agent (array of strings)';
COMMENT ON COLUMN prdoc_summaries.files_summarised IS 'Count of changed files the agent considered';
COMMENT ON COLUMN prdoc_summaries.status IS 'pending | running | completed | failed';

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
