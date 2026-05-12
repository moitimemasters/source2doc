#!/usr/bin/env bash
# Generate a Fernet-compatible (url-safe base64, 32 random bytes) encryption key.
# Usage:  ./generate-encryption-key.sh

set -euo pipefail

run_python() {
    if python3 -c "import cryptography" 2>/dev/null; then
        python3 -c "$1"
    elif command -v uv >/dev/null 2>&1; then
        uv run --quiet --with cryptography python -c "$1"
    else
        echo "error: need python3 with cryptography installed, or uv. Try:" >&2
        echo "  pip3 install cryptography" >&2
        echo "  # or install uv: https://docs.astral.sh/uv/" >&2
        exit 1
    fi
}

run_python 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
