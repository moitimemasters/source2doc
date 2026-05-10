-- Per-file SHA-256 hashes recorded after each docgen ingest run.
--
-- Lets the next ingest skip chunking + embedding for files that haven't
-- changed since the previous generation, and reuse their existing Qdrant
-- points (copied across collections). Closes ТЗ ИНТ-04 / ИНД-06 (B2.4).
--
-- One row per (generation_id, file_path). The (repository_id, file_path)
-- index drives the "latest hash for this file in this repo" lookup that
-- the incremental pipeline issues at the start of every ingest.
--
-- Pre-prod / docker-compose / disposable data — no downgrade.

CREATE TABLE IF NOT EXISTS repo_file_hashes (
    id BIGSERIAL PRIMARY KEY,
    repository_id UUID NOT NULL,
    generation_id UUID NOT NULL,
    file_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    chunks_count INT NOT NULL DEFAULT 0,
    indexed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (generation_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_repo_file_hashes_lookup
    ON repo_file_hashes(repository_id, file_path);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO docgen;
