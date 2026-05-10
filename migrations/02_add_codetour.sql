CREATE TABLE IF NOT EXISTS codetours (
    tour_id UUID PRIMARY KEY,
    generation_id UUID NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    steps JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Create indexes separately (PostgreSQL syntax)
CREATE INDEX IF NOT EXISTS idx_codetours_generation_id ON codetours(generation_id);
CREATE INDEX IF NOT EXISTS idx_codetours_created_at ON codetours(created_at);

COMMENT ON TABLE codetours IS 'Generated code tours for documentation';
COMMENT ON COLUMN codetours.tour_id IS 'Unique identifier for the code tour';
COMMENT ON COLUMN codetours.generation_id IS 'Reference to the documentation generation';
COMMENT ON COLUMN codetours.title IS 'Title of the code tour';
COMMENT ON COLUMN codetours.description IS 'Description of what the tour covers';
COMMENT ON COLUMN codetours.steps IS 'Array of tour steps with file references and explanations';
COMMENT ON COLUMN codetours.metadata IS 'Additional metadata (qdrant collection, etc.)';
