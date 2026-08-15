#!/usr/bin/env bash
# ready.sh — list issues that are actually workable right now.
#
# An issue is "ready" when all of these hold:
#   - it is open
#   - no OPEN issue blocks it (native GitHub blocked-by dependency)
#   - no open PR is set to close it
#   - no unexpired local claim exists for it
#
# This is the `bd ready` equivalent. GitHub can filter FOR blocked issues but
# has no native "give me the unblocked ones" query, so it is computed here.
#
# Requires: gh >= 2.94.0 (blockedBy/blocking JSON fields), jq
# Usage: ready.sh [--repo owner/repo] [--limit N] [--label L] [--json]

set -euo pipefail

REPO=""; LIMIT=100; LABEL=""; AS_JSON=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo)  REPO="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --json)  AS_JSON=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v gh >/dev/null || { echo "gh not found" >&2; exit 127; }
command -v jq >/dev/null || { echo "jq not found" >&2; exit 127; }

# Fail loudly on an old gh. An unsupported --json field makes gh error out, but
# a partially-supported one could return null and silently report blocked work
# as ready. That is the one wrong answer this script must never give.
GH_VER="$(gh --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
if [ "$(printf '%s\n2.94.0\n' "$GH_VER" | sort -V | head -1)" != "2.94.0" ]; then
  echo "gh $GH_VER is too old; need >= 2.94.0 for blockedBy/blocking fields" >&2
  exit 1
fi

[ -n "$REPO" ] || REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

STATE_DIR="${GH_ISSUE_TRACKER_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/gh-issue-tracker}"
CLAIMS="$STATE_DIR/claims-${REPO//\//-}.json"
mkdir -p "$STATE_DIR"
[ -f "$CLAIMS" ] || echo '{}' > "$CLAIMS"

CLAIM_TTL="${GH_ISSUE_TRACKER_CLAIM_TTL:-7200}"   # seconds; default 2h
NOW="$(date +%s)"

CLAIMED="$(jq -r --argjson now "$NOW" --argjson ttl "$CLAIM_TTL" \
  'to_entries[] | select(($now - (.value.ts // 0)) < $ttl) | .key' "$CLAIMS" \
  | sort -u || true)"

# Issues an open PR is set to close.
PR_LINKED="$(gh pr list --repo "$REPO" --state open --limit 200 \
  --json closingIssuesReferences \
  -q '.[].closingIssuesReferences[]?.number' 2>/dev/null | sort -u || true)"

ARGS=(--repo "$REPO" --state open --limit "$LIMIT"
      --json number,title,labels,url,assignees,blockedBy)
[ -n "$LABEL" ] && ARGS+=(--label "$LABEL")

gh issue list "${ARGS[@]}" \
| jq --arg claimed "$CLAIMED" --arg prlinked "$PR_LINKED" '
    ($claimed  | split("\n") | map(select(length>0) | tonumber)) as $c |
    ($prlinked | split("\n") | map(select(length>0) | tonumber)) as $p |

    # blockedBy is a GraphQL connection object {nodes, totalCount}. Accept a
    # bare array too, in case the shape differs across gh versions.
    def blockers:
      (.blockedBy // {})
      | if   type == "array"  then .
        elif type == "object" then (.nodes // [])
        else [] end;

    # A blocker counts as active when it is OPEN, or when its state is absent
    # and we therefore cannot prove it is closed. Erring toward "still blocked"
    # keeps a blocked issue out of the queue rather than handing an agent work
    # it cannot finish.
    def active_blockers:
      [ blockers[] | select((.state // "OPEN") == "OPEN") ];

    [ .[]
      | select( (active_blockers | length) == 0 )
      | select( (.number as $n | $c | index($n)) | not )
      | select( (.number as $n | $p | index($n)) | not )
      | { number, title, url,
          labels: [.labels[]?.name],
          assignees: [.assignees[]?.login] }
    ]' \
| if [ "$AS_JSON" = 1 ]; then cat; else
    jq -r 'if length == 0 then "No ready issues." else
             .[] | "#\(.number)  \(.title)\(if (.labels|length)>0 then "  [" + (.labels|join(",")) + "]" else "" end)"
           end'
  fi
