#!/usr/bin/env bash
# prime.sh — emit the gh-issue-tracker working rules plus current backlog state.
#
# Designed to be small. This lands in agent context every session, so it stays
# under ~20 lines of prose and spends its budget on live state rather than
# restating the CLI (the skill and `gh --help` cover that).
#
# Exits silently (rc 0, no output) when this isn't a gh-issue-tracker repo or gh
# isn't authenticated, so it's safe to wire unconditionally into a SessionStart
# hook across many repos.
#
# Usage: prime.sh [--repo owner/repo]

set -euo pipefail

REPO=""
[ "${1:-}" = "--repo" ] && { REPO="$2"; shift 2; }

# Silent no-op unless everything we need is present.
command -v gh >/dev/null 2>&1 || exit 0
command -v jq >/dev/null 2>&1 || exit 0
gh auth status >/dev/null 2>&1 || exit 0
[ -n "$REPO" ] || REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" || exit 0
[ -n "$REPO" ] || exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Live state. Failures here degrade to empty rather than blocking the session.
READY_JSON="$("$HERE/ready.sh" --repo "$REPO" --json 2>/dev/null || echo '[]')"
READY_N="$(printf '%s' "$READY_JSON" | jq 'length' 2>/dev/null || echo 0)"
MINE="$(gh issue list --repo "$REPO" --state open --assignee @me \
        --json number,title -q '.[] | "#\(.number) \(.title)"' 2>/dev/null || true)"

cat <<EOF
## Work tracking for $REPO

Durable work lives in GitHub Issues. Use TodoWrite for steps within this
session; use issues for anything that outlives it. They serve different
purposes and both are fine.

- Find work: \`$HERE/ready.sh\` (open, unblocked, unclaimed). Do not hand-roll
  this query — blockedBy is a connection object and getting it wrong reports
  blocked work as ready.
- Claim before starting: \`gh issue edit <n> --add-assignee @me\`
- Relationships are native flags on create/edit: \`--blocked-by\`, \`--blocking\`,
  \`--parent\`. They exist as of gh 2.94.0. Never write "Blocked by: #12" into an
  issue body — that is a mention, not a relationship, and nothing can query it.
- Amend a spec by posting a comment, not by editing the issue body. Body edits
  have no conditional-write support and silently clobber concurrent writers.
- Close via the PR: put \`Fixes $REPO#<n>\` in the PR body so the causal link is
  recorded.
EOF

echo
echo "Ready now: $READY_N"
if [ -n "$MINE" ]; then
  echo "Assigned to you:"
  printf '%s\n' "$MINE" | sed 's/^/  /'
fi
