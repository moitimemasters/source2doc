-- Page-link graph (B13.2 / partial ТЗ АГТ-06).
--
-- Sits on top of the symbol map from migration 13 (`page_symbols`):
-- after every page is persisted, the finalize handler scans its body
-- for symbol mentions and records a directed edge to the symbol's
-- home page. Together the two tables form a lightweight relationship
-- graph used by the wiki UI ("Referenced by …") and by the gateway
-- ``GET /api/v1/wiki/{generation_id}/graph`` endpoint.
--
-- Edges are scoped per ``generation_id`` so a re-run starts from a
-- clean slate; the unique key collapses duplicates from the same
-- generation while letting the upsert bump ``weight``.

CREATE TABLE IF NOT EXISTS page_links (
    id BIGSERIAL PRIMARY KEY,
    generation_id UUID NOT NULL,
    from_page_id TEXT NOT NULL,
    to_page_id TEXT NOT NULL,
    kind TEXT NOT NULL,             -- 'symbol' | 'mention' | 'inferred'
    weight INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (generation_id, from_page_id, to_page_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_page_links_from
    ON page_links(generation_id, from_page_id);

CREATE INDEX IF NOT EXISTS idx_page_links_to
    ON page_links(generation_id, to_page_id);

COMMENT ON TABLE page_links IS
    'Directed graph of cross-page references; rebuilt per generation.';
COMMENT ON COLUMN page_links.kind IS
    'How the edge was inferred: symbol (resolved via page_symbols), mention (string match), inferred (heuristic).';
COMMENT ON COLUMN page_links.weight IS
    'Aggregated count of mentions; bumped on conflict via ON CONFLICT DO UPDATE.';

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
