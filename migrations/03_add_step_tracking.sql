CREATE TABLE IF NOT EXISTS generation_steps (
    id SERIAL PRIMARY KEY,
    generation_id UUID NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    error_type VARCHAR(255),
    error_is_transient BOOLEAN DEFAULT FALSE,
    attempt_number INTEGER DEFAULT 1,
    max_attempts INTEGER DEFAULT 3,
    step_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_generation_step UNIQUE (generation_id, step_name),
    CONSTRAINT valid_step_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_steps_generation_id ON generation_steps(generation_id);
CREATE INDEX IF NOT EXISTS idx_steps_status ON generation_steps(status);

DROP TRIGGER IF EXISTS update_generation_steps_updated_at ON generation_steps;
CREATE TRIGGER update_generation_steps_updated_at
    BEFORE UPDATE ON generation_steps
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE IF EXISTS generation_tasks ADD COLUMN IF NOT EXISTS last_completed_step VARCHAR(255);
ALTER TABLE IF EXISTS generation_tasks ADD COLUMN IF NOT EXISTS step_data JSONB DEFAULT '{}'::jsonb;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO docgen;
