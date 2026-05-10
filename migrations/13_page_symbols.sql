-- Cross-page link index. Closes ТЗ ДОК-08 (B6.2).
--
-- For every persisted documentation page we extract a small set of "symbols"
-- (titles, headings, identifier-like backticked strings) so the wiki frontend
-- can promote inline mentions to hyperlinks pointing at the symbol's home
-- page. The table is rebuilt on each generation; lookups are case-insensitive
-- via the ``lower(symbol)`` index.

CREATE TABLE IF NOT EXISTS page_symbols (
    id BIGSERIAL PRIMARY KEY,
    generation_id UUID NOT NULL,
    page_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,           -- 'page_title' | 'function' | 'class' | 'module'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_page_symbols_lookup
    ON page_symbols(generation_id, lower(symbol));

CREATE INDEX IF NOT EXISTS idx_page_symbols_generation
    ON page_symbols(generation_id);

COMMENT ON TABLE page_symbols IS
    'Cross-page link index: maps a symbol (title / function / class / module) to its home page.';
COMMENT ON COLUMN page_symbols.symbol IS
    'Symbol string as it appears in source content; lookups go through lower(symbol).';
COMMENT ON COLUMN page_symbols.kind IS
    'One of: page_title, function, class, module.';

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
