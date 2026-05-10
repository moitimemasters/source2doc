-- Drop legacy task/step tracking tables.
-- Stream events (Redis streams) are the single source of truth for generation status.

DROP TABLE IF EXISTS generation_steps CASCADE;
DROP TABLE IF EXISTS generation_tasks CASCADE;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO docgen;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO docgen;
