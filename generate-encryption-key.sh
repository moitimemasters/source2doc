#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: ./generate-encryption-key.sh <passphrase>"
    echo "Example: ./generate-encryption-key.sh my-secret-key"
    exit 1
fi

PASSPHRASE="$1"

KEY=$(echo -n "$PASSPHRASE" | openssl dgst -sha256 -binary | base64)

echo "Generated Fernet-compatible encryption key:"
echo "$KEY"
echo ""
echo "Add this to your .env file:"
echo "ENCRYPTION_KEY=$KEY"
