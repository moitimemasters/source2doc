#!/usr/bin/env bash
# Generate bcrypt hash for the gateway's admin_password_hash field.
# Usage:  ./generate-admin-password.sh <password>
# Or run without args and the script will prompt (no echo).

set -euo pipefail

if [ "${1-}" ]; then
    PW="$1"
else
    read -rsp "Admin password: " PW && echo
fi

if [ -z "$PW" ]; then
    echo "error: empty password" >&2
    exit 1
fi

run_python() {
    if python3 -c "import bcrypt" 2>/dev/null; then
        python3 -c "$1"
    elif command -v uv >/dev/null 2>&1; then
        uv run --quiet --with bcrypt python -c "$1"
    else
        echo "error: need python3 with bcrypt installed, or uv. Try:" >&2
        echo "  pip3 install bcrypt" >&2
        echo "  # or install uv: https://docs.astral.sh/uv/" >&2
        exit 1
    fi
}

HASH=$(PW="$PW" run_python '
import os, bcrypt
print(bcrypt.hashpw(os.environ["PW"].encode(), bcrypt.gensalt()).decode())
')

echo "$HASH"
