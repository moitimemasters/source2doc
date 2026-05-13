#!/usr/bin/env bash
# Generates a fresh `.env` with a random Fernet encryption key + bcrypt admin
# password hash. Idempotent — refuses to overwrite an existing `.env`.
#
# Usage:  ./bootstrap.sh
#
# After running, start the stack with:
#   docker compose --profile app up -d --build

set -euo pipefail

cd "$(dirname "$0")"

if [ -f .env ]; then
    echo ".env already exists — refusing to overwrite. Delete it first if you want a fresh bootstrap." >&2
    exit 1
fi

gen_password() {
    # head closes early -> tr gets SIGPIPE; we accept that explicitly so
    # `set -o pipefail` doesn't kill the bootstrap.
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 16 || true
}
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(gen_password)}"

# Returns 0 when something is already listening on $1 (TCP, loopback).
# Uses bash's /dev/tcp so we don't depend on lsof / ss / nc being installed.
# The subshell scope makes the FD self-close on exit; we never see FD3 here.
port_in_use() {
    local port=$1
    if (: < /dev/tcp/127.0.0.1/"$port") 2>/dev/null; then
        return 0
    fi
    return 1
}

# Prompts for a host port for a stack component. Tries the default first;
# if it's busy, asks the user for an alternate (or accepts the busy value
# anyway — Docker will fail loudly at `up` time if it really collides).
# Non-interactive mode (NONINTERACTIVE=1 or stdin not a TTY) skips the
# prompt and just warns about conflicts.
pick_port() {
    local var_name=$1 default=$2 description=$3
    local chosen=$default

    if port_in_use "$default"; then
        if [ "${NONINTERACTIVE:-0}" = "1" ] || [ ! -t 0 ]; then
            echo "  WARN: ${description} default :${default} is already in use — ${var_name} unset, docker may fail to bind." >&2
        else
            echo "  ${description} default :${default} is already in use." >&2
            while true; do
                read -r -p "    Pick another port for ${var_name} (blank to keep ${default}): " chosen </dev/tty
                chosen=${chosen:-$default}
                if ! [[ $chosen =~ ^[0-9]+$ ]] || [ "$chosen" -lt 1 ] || [ "$chosen" -gt 65535 ]; then
                    echo "    invalid port: $chosen" >&2
                    chosen=$default
                    continue
                fi
                if [ "$chosen" != "$default" ] && port_in_use "$chosen"; then
                    echo "    :$chosen is also in use, try again" >&2
                    continue
                fi
                break
            done
        fi
    fi

    printf -v "$var_name" '%s' "$chosen"
}

# Asks one yes/no question and prints `y` / `n` on stdout. Same TTY rules
# as pick_port — under NONINTERACTIVE or no TTY the default wins silently.
ask_yes_no() {
    local prompt=$1 default=$2 answer
    if [ "${NONINTERACTIVE:-0}" = "1" ] || [ ! -t 0 ]; then
        echo "$default"
        return
    fi
    while true; do
        local hint
        if [ "$default" = "y" ]; then hint="[Y/n]"; else hint="[y/N]"; fi
        read -r -p "  ${prompt} ${hint}: " answer </dev/tty
        answer=${answer:-$default}
        case "$answer" in
            y|Y|yes|YES) echo "y"; return ;;
            n|N|no|NO)   echo "n"; return ;;
            *) echo "    answer y or n" >&2 ;;
        esac
    done
}

# Compose overrides live in deploy/overrides/. Bootstrap toggles them by
# writing COMPOSE_FILE into .env so `docker compose` picks them up
# automatically. Multiple overrides chain with ":".
COMPOSE_FILES="docker-compose.yml"
echo "Overrides..."
if [ "$(ask_yes_no "Enable IPv6 networking (deploy/overrides/ipv6.yml — corp VPN / AAAA-only endpoints)?" n)" = "y" ]; then
    COMPOSE_FILES="$COMPOSE_FILES:deploy/overrides/ipv6.yml"
fi
# Auto-pick up a user-local override (gitignored) when present. Setting
# COMPOSE_FILE explicitly disables compose's implicit auto-load, so we
# re-add it here to preserve the historical behaviour.
if [ -f docker-compose.override.yml ]; then
    echo "  Detected docker-compose.override.yml — including in the chain."
    COMPOSE_FILES="$COMPOSE_FILES:docker-compose.override.yml"
fi

echo "Checking host ports..."
pick_port TRAEFIK_HTTP_PORT       80   "Traefik HTTP (UI + API ingress)"
pick_port TRAEFIK_DASHBOARD_PORT  8080 "Traefik dashboard"
pick_port POSTGRES_HOST_PORT      5432 "Postgres"
pick_port REDIS_HOST_PORT         6379 "Redis"
pick_port QDRANT_HOST_PORT        6333 "Qdrant HTTP"
pick_port QDRANT_GRPC_HOST_PORT   6334 "Qdrant gRPC"
pick_port LOCALSTACK_HOST_PORT    4566 "LocalStack"
pick_port PGADMIN_HOST_PORT       5050 "pgAdmin"

echo "Generating encryption key..."
ENCRYPTION_KEY=$(./generate-encryption-key.sh)

echo "Hashing admin password..."
ADMIN_PASSWORD_HASH=$(./generate-admin-password.sh "$ADMIN_PASSWORD")

# Docker Compose interpolates `$` in env_file values. bcrypt hashes are full
# of literal `$` (`$2b$12$...`) which compose would otherwise expand against
# empty shell vars and silently corrupt. Double them so compose round-trips
# the hash to the container env unchanged.
ADMIN_PASSWORD_HASH_ESCAPED=${ADMIN_PASSWORD_HASH//\$/\$\$}

cat > .env <<EOF
# Generated by ./bootstrap.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ).
# Re-run by deleting this file and running ./bootstrap.sh again.

# Fernet key. Used by gateway + workers to encrypt/decrypt per-task LLM configs
# in Redis and admin presets in Postgres. MUST match across all services.
ENCRYPTION_KEY=$ENCRYPTION_KEY

# bcrypt hash of the admin password (literal \$ doubled because Docker Compose
# interpolates env_file values). Plaintext was printed once on bootstrap.
ADMIN_PASSWORD_HASH=$ADMIN_PASSWORD_HASH_ESCAPED

# PostgreSQL password — shared by the postgres container, gateway, and workers.
POSTGRES_PASSWORD=docgen_password

# Compose file chain — picks up files from deploy/overrides/. Edit to
# toggle overrides without re-running bootstrap.
COMPOSE_FILE=$COMPOSE_FILES

# Host-side port mappings for the compose stack. Edit and re-up to remap.
# In-cluster traffic uses service names, so these only affect external access.
TRAEFIK_HTTP_PORT=$TRAEFIK_HTTP_PORT
TRAEFIK_DASHBOARD_PORT=$TRAEFIK_DASHBOARD_PORT
POSTGRES_HOST_PORT=$POSTGRES_HOST_PORT
REDIS_HOST_PORT=$REDIS_HOST_PORT
QDRANT_HOST_PORT=$QDRANT_HOST_PORT
QDRANT_GRPC_HOST_PORT=$QDRANT_GRPC_HOST_PORT
LOCALSTACK_HOST_PORT=$LOCALSTACK_HOST_PORT
PGADMIN_HOST_PORT=$PGADMIN_HOST_PORT
EOF

cat <<EOF

============================================================
.env generated.

Admin login:
  username: admin
  password: $ADMIN_PASSWORD

SAVE THIS PASSWORD NOW — it is not stored anywhere else.

Next step:
  docker compose --profile app up -d --build

Then open http://localhost:${TRAEFIK_HTTP_PORT}/ and log in at /admin/login.
============================================================
EOF
