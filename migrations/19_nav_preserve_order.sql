-- Preserve insertion order of the navigation map.
--
-- ``documentation_index.navigation`` was originally JSONB. JSONB stores
-- objects as a parsed/sorted representation, so reading the column back
-- returns keys in alphabetical order — which the wiki UI then renders as
-- the page list, scrambling the planner's intent.
--
-- JSON (text-mode) preserves the literal bytes, so insertion order is
-- kept. We don't query into ``navigation`` server-side, only round-trip
-- it as a blob for the UI, so dropping JSONB's indexing/operator support
-- has no downside.

ALTER TABLE documentation_index
    ALTER COLUMN navigation TYPE JSON
    USING navigation::text::json;
