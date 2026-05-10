-- 07_boxed_mode.sql
-- Boxed deployment mode: server-side LLM/embeddings/qdrant presets pre-configured
-- by an admin, plus a session table for admin auth.
--
-- The presets table holds Fernet-encrypted JSON of {llm, embeddings, qdrant};
-- the gateway uses the existing `encryption_key` (shared with Redis user-config
-- encryption) to encrypt/decrypt. End-user requests omit credentials and the
-- gateway resolves them from the default preset.

CREATE TABLE IF NOT EXISTS config_presets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT,
    encrypted_config TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Partial unique index — at most one preset can be marked default.
CREATE UNIQUE INDEX IF NOT EXISTS ux_config_presets_one_default
    ON config_presets ((is_default))
    WHERE is_default = TRUE;

DROP TRIGGER IF EXISTS update_config_presets_updated_at ON config_presets;
CREATE TRIGGER update_config_presets_updated_at
    BEFORE UPDATE ON config_presets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash CHAR(64) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires_at
    ON admin_sessions (expires_at);

GRANT ALL PRIVILEGES ON config_presets TO docgen;
GRANT ALL PRIVILEGES ON admin_sessions TO docgen;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO docgen;
