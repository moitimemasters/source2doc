-- Iterative documentation generation (CI-style incremental rebuild).
--
-- The full-mode docgen pipeline is "all or nothing": ingest, plan, write
-- every page, finalize. Iterative mode lets a caller submit only the set
-- of files that changed since a base bundle, and the worker:
--
--   * copies pages whose source files were untouched (verbatim, with a new
--     ``page_versions`` snapshot under the new ``generation_id``);
--   * rewrites pages whose source files appear in ``changed_files`` (writer
--     runs in update-mode with the prior body + diff context);
--   * marks pages whose source files were entirely deleted as deprecated;
--   * runs a small "orphan planner" against changed_files that no existing
--     page covers, producing fresh page specs for the writer to author;
--   * always re-runs ``finalize`` to rebuild the symbol/link graph and
--     create a new ``documentation_bundles`` row that points back at the
--     base via ``parent_generation_id``.
--
-- Schema additions:
--
--   * ``documentation_bundles.parent_generation_id`` — lineage column. Null
--     for full-mode bundles, set on iterative bundles to the base bundle's
--     ``generation_id``.
--   * ``documentation_bundles.generation_mode`` — 'full' (default) or
--     'incremental'. Lets the wiki UI render a "Updated incrementally from …"
--     header and lets analytics compare cost between modes.
--   * ``documentation_pages.source_files`` — array of repo-relative file
--     paths the writer used as RAG/read-file context. Populated by the
--     writer handler from ``DocGenDeps.file_cache`` plus the page's
--     ``metadata.source_refs``. Drives the iterative-mode classifier
--     (overlap with ``changed_files`` ⇒ rewrite the page).
--   * ``documentation_pages.deprecated`` — soft-delete flag. Pages whose
--     source files were entirely deleted between runs are copied into the
--     new bundle with this flag set so the wiki can grey them out instead
--     of hard-deleting (preserves history; deep-links keep working).
--
-- Pre-prod / docker-compose / disposable data — no downgrade.

ALTER TABLE documentation_bundles
    ADD COLUMN IF NOT EXISTS parent_generation_id UUID,
    ADD COLUMN IF NOT EXISTS generation_mode TEXT
        NOT NULL DEFAULT 'full'
        CHECK (generation_mode IN ('full', 'incremental'));

CREATE INDEX IF NOT EXISTS idx_bundles_parent_generation_id
    ON documentation_bundles(parent_generation_id);

ALTER TABLE documentation_pages
    ADD COLUMN IF NOT EXISTS source_files TEXT[],
    ADD COLUMN IF NOT EXISTS deprecated BOOLEAN NOT NULL DEFAULT FALSE;

-- GIN index on TEXT[] supports the && (overlap) operator used by the
-- iterative classifier to find pages whose source_files intersect a
-- ``changed_files`` array. Without this the classifier scans every page.
CREATE INDEX IF NOT EXISTS idx_pages_source_files
    ON documentation_pages USING GIN (source_files);

CREATE INDEX IF NOT EXISTS idx_pages_deprecated
    ON documentation_pages(deprecated)
    WHERE deprecated = TRUE;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO docgen;
