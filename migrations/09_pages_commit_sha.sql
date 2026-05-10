-- Persist the source-repo commit SHA on every generated page so the wiki
-- viewer can link a page back to the exact code revision it was written
-- against. The column is nullable because uploads without a `.git`
-- directory (plain archives) carry no SHA.
--
-- We also store the SHA on the `repositories` row at clone-time so the
-- docgen worker can fetch it once and propagate it to every page in the
-- bundle without re-shelling out to git.
--
-- Naming follows the convention already used in `core/shared/source2doc/
-- git_context.py` (CommitRef.sha) — `commit_sha` rather than
-- `commit_hash`.

ALTER TABLE repositories
    ADD COLUMN IF NOT EXISTS commit_sha TEXT;

ALTER TABLE documentation_pages
    ADD COLUMN IF NOT EXISTS commit_sha TEXT;

-- Mirrors the lookup-column indexing pattern used in earlier migrations
-- (see idx_pages_status in 08_page_status.sql).
CREATE INDEX IF NOT EXISTS idx_pages_commit_sha
    ON documentation_pages(commit_sha);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
