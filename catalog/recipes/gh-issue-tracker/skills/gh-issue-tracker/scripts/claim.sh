#!/usr/bin/env bash
# claim.sh — soft, expiring, machine-local work claims.
#
# Why this exists: GitHub assignees are the durable signal, but they are a
# round trip and they linger if an agent dies mid-task. A claim file gives
# concurrent agents on one machine a cheap "someone is already on this" check
# that self-heals after CLAIM_TTL, so a crashed pod cannot wedge an issue.
#
# Claims are advisory and machine-local. They do NOT coordinate across hosts.
# For durable ownership use `gh issue edit <n> --add-assignee @me`.
#
# Adapted from the claim-file pattern in openclaw/openclaw skills/gh-issues
# (MIT, Copyright (c) 2026 OpenClaw Foundation).
#
# Usage:
#   claim.sh take <issue-number> [--repo owner/repo] [--who name]
#   claim.sh release <issue-number> [--repo owner/repo]
#   claim.sh list [--repo owner/repo]

set -euo pipefail

CMD="${1:-}"; shift || true
NUM=""
case "$CMD" in
  take|release) NUM="${1:-}"; shift || true ;;
  list) ;;
  *) echo "usage: claim.sh {take|release} <issue-number> | list" >&2; exit 2 ;;
esac

REPO=""; WHO="${GH_ISSUE_TRACKER_AGENT:-$(hostname 2>/dev/null || echo agent)}"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --who)  WHO="$2";  shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v jq >/dev/null || { echo "jq not found" >&2; exit 127; }
[ -n "$REPO" ] || REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

STATE_DIR="${GH_ISSUE_TRACKER_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/gh-issue-tracker}"
CLAIMS="$STATE_DIR/claims-${REPO//\//-}.json"
CLAIM_TTL="${GH_ISSUE_TRACKER_CLAIM_TTL:-7200}"
mkdir -p "$STATE_DIR"
[ -f "$CLAIMS" ] || echo '{}' > "$CLAIMS"

NOW="$(date +%s)"
TMP="$(mktemp "${CLAIMS}.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

case "$CMD" in
  take)
    [ -n "$NUM" ] || { echo "issue number required" >&2; exit 2; }
    # Refuse if a live claim is held by someone else; expired claims are free.
    HOLDER="$(jq -r --arg n "$NUM" --argjson now "$NOW" --argjson ttl "$CLAIM_TTL" \
      '.[$n] // empty | select(($now - (.ts // 0)) < $ttl) | .who // "unknown"' "$CLAIMS")"
    if [ -n "$HOLDER" ] && [ "$HOLDER" != "$WHO" ]; then
      echo "issue #$NUM already claimed by $HOLDER" >&2; exit 1
    fi
    jq --arg n "$NUM" --arg who "$WHO" --argjson ts "$NOW" \
       '.[$n] = {who: $who, ts: $ts}' "$CLAIMS" > "$TMP" && mv "$TMP" "$CLAIMS"
    echo "claimed #$NUM as $WHO"
    ;;
  release)
    [ -n "$NUM" ] || { echo "issue number required" >&2; exit 2; }
    jq --arg n "$NUM" 'del(.[$n])' "$CLAIMS" > "$TMP" && mv "$TMP" "$CLAIMS"
    echo "released #$NUM"
    ;;
  list)
    jq -r --argjson now "$NOW" --argjson ttl "$CLAIM_TTL" \
      'to_entries[] | "\(if ($now - (.value.ts // 0)) < $ttl then "LIVE   " else "EXPIRED" end) #\(.key)  \(.value.who)"' \
      "$CLAIMS"
    ;;
esac
