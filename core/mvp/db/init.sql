-- Database initialization script for documentation storage

-- Create documentation_bundles table
CREATE TABLE IF NOT EXISTS documentation_bundles (
    id SERIAL PRIMARY KEY,
    generation_id UUID NOT NULL UNIQUE,
    project_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT unique_generation_id UNIQUE (generation_id)
);

-- Create documentation_index table (stores index.json)
CREATE TABLE IF NOT EXISTS documentation_index (
    id SERIAL PRIMARY KEY,
    bundle_id INTEGER NOT NULL REFERENCES documentation_bundles(id) ON DELETE CASCADE,
    version VARCHAR(50) NOT NULL DEFAULT '1.0',
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    navigation JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_bundle_index UNIQUE (bundle_id)
);

-- Create documentation_pages table (stores individual pages)
CREATE TABLE IF NOT EXISTS documentation_pages (
    id SERIAL PRIMARY KEY,
    bundle_id INTEGER NOT NULL REFERENCES documentation_bundles(id) ON DELETE CASCADE,
    page_id VARCHAR(255) NOT NULL,
    title VARCHAR(500) NOT NULL,
    summary TEXT,
    content JSONB NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_bundle_page UNIQUE (bundle_id, page_id)
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_bundles_generation_id ON documentation_bundles(generation_id);
CREATE INDEX IF NOT EXISTS idx_bundles_created_at ON documentation_bundles(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pages_bundle_id ON documentation_pages(bundle_id);
CREATE INDEX IF NOT EXISTS idx_pages_page_id ON documentation_pages(page_id);
CREATE INDEX IF NOT EXISTS idx_pages_bundle_page ON documentation_pages(bundle_id, page_id);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
CREATE TRIGGER update_documentation_bundles_updated_at
    BEFORE UPDATE ON documentation_bundles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_documentation_pages_updated_at
    BEFORE UPDATE ON documentation_pages
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO docgen;
