CREATE TABLE IF NOT EXISTS repositories (
    id SERIAL PRIMARY KEY,
    repo_id UUID NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL DEFAULT 'upload',
    git_url VARCHAR(1024),
    git_branch VARCHAR(255),
    s3_key VARCHAR(1024),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT valid_source_type CHECK (source_type IN ('upload', 'git'))
);

CREATE INDEX IF NOT EXISTS idx_repositories_repo_id ON repositories(repo_id);
CREATE INDEX IF NOT EXISTS idx_repositories_name ON repositories(name);
CREATE INDEX IF NOT EXISTS idx_repositories_created_at ON repositories(created_at DESC);

DROP TRIGGER IF EXISTS update_repositories_updated_at ON repositories;
CREATE TRIGGER update_repositories_updated_at
    BEFORE UPDATE ON repositories
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE IF EXISTS generation_tasks ADD COLUMN IF NOT EXISTS name VARCHAR(500);
ALTER TABLE IF EXISTS generation_tasks ADD COLUMN IF NOT EXISTS description TEXT;

ALTER TABLE documentation_bundles ADD COLUMN IF NOT EXISTS name VARCHAR(500);
ALTER TABLE documentation_bundles ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE documentation_bundles ADD COLUMN IF NOT EXISTS repo_id UUID;

CREATE INDEX IF NOT EXISTS idx_bundles_name ON documentation_bundles(name);
CREATE INDEX IF NOT EXISTS idx_bundles_repo_id ON documentation_bundles(repo_id);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO docgen;
