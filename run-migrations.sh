#!/bin/bash
set -e

# Database connection parameters
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-docgen}"
DB_USER="${POSTGRES_USER:-docgen}"
DB_PASSWORD="${POSTGRES_PASSWORD:-docgen_password}"

# Construct connection string
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "Running migrations..."
echo "Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}"

# Check if sqlx is installed
if ! command -v sqlx &> /dev/null; then
    echo "Error: sqlx-cli is not installed"
    echo "Install it with: cargo install sqlx-cli --no-default-features --features postgres"
    exit 1
fi

# Run migrations
cd "$(dirname "$0")"
sqlx migrate run --database-url "${DATABASE_URL}" --source ./migrations

echo "Migrations completed successfully!"
