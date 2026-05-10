#!/bin/sh
# Merge any extra CA bundles mounted under /certs/*.pem with the system CA
# bundle so internal corp roots (e.g. Yandex) are trusted by Python's ssl
# stack (httpx, openai client, etc.).
SYSTEM_CA="/etc/ssl/certs/ca-certificates.crt"
EXTRA_CA_DIR="/certs"
COMBINED_CA="/tmp/ca-bundle.pem"

if [ -d "$EXTRA_CA_DIR" ] && ls "$EXTRA_CA_DIR"/*.pem >/dev/null 2>&1; then
    cat "$SYSTEM_CA" "$EXTRA_CA_DIR"/*.pem > "$COMBINED_CA"
    export SSL_CERT_FILE="$COMBINED_CA"
    export REQUESTS_CA_BUNDLE="$COMBINED_CA"
    # curl + libcurl-based clients (some MkDocs / Sphinx tooling) read this.
    export CURL_CA_BUNDLE="$COMBINED_CA"

    # Make the same vars available to interactive `docker exec` shells. PID 1's
    # environ otherwise stays unreadable to new shells, which historically made
    # debugging Yandex calls inside the container fail with cert errors that
    # don't reproduce in the worker process itself.
    cat > /etc/profile.d/source2doc-ca.sh <<EOF
export SSL_CERT_FILE="$COMBINED_CA"
export REQUESTS_CA_BUNDLE="$COMBINED_CA"
export CURL_CA_BUNDLE="$COMBINED_CA"
EOF
    chmod 0644 /etc/profile.d/source2doc-ca.sh
fi

exec env WORKER_ID="${WORKER_ID:-${HOSTNAME}}" "$@"
