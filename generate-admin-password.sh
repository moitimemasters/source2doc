#!/usr/bin/env bash
# Generate a bcrypt hash for the gateway's admin_password_hash field.
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

HASH=$(python3 - <<PY
import sys, bcrypt
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())
PY
"$PW")

echo "Generated bcrypt hash:"
echo "$HASH"
echo ""
echo "Add this to core/gateway/config.yaml:"
echo "admin_password_hash: \"$HASH\""
