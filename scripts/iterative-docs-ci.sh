#!/usr/bin/env bash
# Iterative-docs CI primitive.
#
# Logs into the gateway, submits an iterative-mode docgen task, polls
# for completion, and prints the new generation_id to stdout. Designed
# for GitHub Actions / GitLab CI / any cron-style runner.
#
# Required env vars:
#   GATEWAY_URL              base URL, e.g. https://docs.example.internal
#   ADMIN_USERNAME           gateway admin login (default: admin)
#   ADMIN_PASSWORD           gateway admin password
#   REPO_ID                  repository UUID in the gateway's catalogue
#
# Diff source — exactly one of:
#   FROM_COMMIT + TO_COMMIT  commit range; the worker computes the file
#                            diff itself via GitContext
#   CHANGED_FILES            comma-separated list of repo-relative paths
#                            (DELETED_FILES is the matching delete list)
#
# Optional:
#   BASE_GENERATION_ID       explicit base bundle; defaults to the latest
#                            bundle for REPO_ID
#   PRESET                   named server-side LLM/embeddings preset; if
#                            unset the request relies on inline llm/...
#                            fields you may inject via $EXTRA_JSON
#   EXTRA_JSON               additional JSON fields merged into the
#                            request body (e.g. inline llm config)
#   DELETED_FILES            comma-separated paths removed since base
#   POLL_TIMEOUT_SECONDS     defaults to 1800 (30 min)
#
# Outputs:
#   stdout:   the new generation_id (single line) on success
#   stderr:   progress + error messages
#   exit 0:   success
#   exit !=0: failure (auth / API / poll timeout / task.failed)

set -euo pipefail

: "${GATEWAY_URL:?GATEWAY_URL required}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD required}"
: "${REPO_ID:?REPO_ID required}"

# Either commit-range mode or explicit-file-list mode — but at least one
# must be present. Both being set is fine: ``changed_files`` takes
# precedence server-side; the commit range is just metadata in that case.
HAS_RANGE=0
HAS_FILES=0
[[ -n "${FROM_COMMIT:-}" && -n "${TO_COMMIT:-}" ]] && HAS_RANGE=1
[[ -n "${CHANGED_FILES:-}" || -n "${DELETED_FILES:-}" ]] && HAS_FILES=1
if [[ $HAS_RANGE -eq 0 && $HAS_FILES -eq 0 ]]; then
    echo "ERROR: provide FROM_COMMIT+TO_COMMIT, CHANGED_FILES, or DELETED_FILES" >&2
    exit 64
fi

ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
POLL_TIMEOUT_SECONDS="${POLL_TIMEOUT_SECONDS:-1800}"

COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

log "logging in as $ADMIN_USERNAME at $GATEWAY_URL"
LOGIN_HTTP=$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST "$GATEWAY_URL/api/v1/admin/auth/login" \
    -H 'Content-Type: application/json' \
    -c "$COOKIE_JAR" \
    -d "{\"username\":\"$ADMIN_USERNAME\",\"password\":\"$ADMIN_PASSWORD\"}")
if [[ "$LOGIN_HTTP" != "200" ]]; then
    log "login failed (HTTP $LOGIN_HTTP)"
    exit 1
fi

# Build the iterative request. Three modes:
#   * commit range only       → worker runs ``git diff`` itself
#   * explicit file list only → worker uses CHANGED_FILES/DELETED_FILES
#   * both                    → ``changed_files`` wins; the SHAs are
#                               just stamped on the new bundle
REQUEST_JSON=$(jq -n \
    --arg repo "$REPO_ID" \
    --arg base "${BASE_GENERATION_ID:-}" \
    --arg from "${FROM_COMMIT:-}" \
    --arg to "${TO_COMMIT:-}" \
    --arg preset "${PRESET:-}" \
    --arg changed "${CHANGED_FILES:-}" \
    --arg deleted "${DELETED_FILES:-}" \
    '{repo_id: $repo}
    + (if $base != "" then {base_generation_id: $base} else {} end)
    + (if $from != "" then {from_commit: $from} else {} end)
    + (if $to != ""   then {to_commit:   $to,   head_sha: $to} else {} end)
    + (if $changed != "" then {changed_files: ($changed | split(",") | map(select(length > 0)))} else {} end)
    + (if $deleted != "" then {deleted_files: ($deleted | split(",") | map(select(length > 0)))} else {} end)
    + (if $preset != "" then {preset: $preset} else {} end)')

if [[ -n "${EXTRA_JSON:-}" ]]; then
    REQUEST_JSON=$(jq -s '.[0] * .[1]' <(echo "$REQUEST_JSON") <(echo "$EXTRA_JSON"))
fi

log "submitting iterative request: $(echo "$REQUEST_JSON" | jq -c '{repo_id, from_commit, to_commit, base_generation_id, preset, changed_files: (.changed_files // [] | length), deleted_files: (.deleted_files // [] | length)}')"

SUBMIT_BODY_FILE="$(mktemp)"
SUBMIT_HTTP=$(curl -sS -o "$SUBMIT_BODY_FILE" -w '%{http_code}' \
    -X POST "$GATEWAY_URL/api/v1/tasks/incremental" \
    -H 'Content-Type: application/json' \
    -b "$COOKIE_JAR" \
    -d "$REQUEST_JSON")
SUBMIT_BODY=$(cat "$SUBMIT_BODY_FILE")
rm -f "$SUBMIT_BODY_FILE"

if [[ "$SUBMIT_HTTP" != "200" ]]; then
    log "submit failed (HTTP $SUBMIT_HTTP): $SUBMIT_BODY"
    exit 2
fi

GENERATION_ID=$(echo "$SUBMIT_BODY" | jq -r '.generation_id')
if [[ -z "$GENERATION_ID" || "$GENERATION_ID" == "null" ]]; then
    log "could not parse generation_id from response: $SUBMIT_BODY"
    exit 3
fi
log "queued: generation_id=$GENERATION_ID"

# Poll until completion. The status field is derived by the gateway
# from event-stream content (see service.get_task_status); ``failed``
# is terminal and means ``task.failed`` was emitted somewhere down the
# pipeline. ``completed`` means ``generation.completed`` fired.
DEADLINE=$(( $(date +%s) + POLL_TIMEOUT_SECONDS ))
LAST_STATUS=""
while [[ $(date +%s) -lt $DEADLINE ]]; do
    sleep 8
    STATUS_BODY=$(curl -sS \
        -X GET "$GATEWAY_URL/api/v1/streams" \
        -b "$COOKIE_JAR")
    STATUS=$(echo "$STATUS_BODY" | jq -r --arg g "$GENERATION_ID" \
        '.streams[] | select(.stream_id==$g) | .status')
    if [[ -z "$STATUS" ]]; then
        STATUS="(not yet visible)"
    fi
    if [[ "$STATUS" != "$LAST_STATUS" ]]; then
        log "status: $STATUS"
        LAST_STATUS="$STATUS"
    fi
    case "$STATUS" in
        completed)
            log "generation completed"
            echo "$GENERATION_ID"
            exit 0
            ;;
        failed)
            log "generation failed — see $GATEWAY_URL/streams/$GENERATION_ID/logs"
            exit 4
            ;;
    esac
done

log "poll timed out after $POLL_TIMEOUT_SECONDS s; last status=$LAST_STATUS"
exit 5
