#!/usr/bin/env bash
# The scheduled pin upgrade (GH-582), run by .github/workflows/pin-upgrade.yml from the repo root.
#
# Runs `harnessed update --yes --no-rebuild`. When a pin moved, lands it on `upgrade-<date>` as an
# API commit, opens that day's PR if none is open, and dispatches the checks.
#
# API COMMITS, NEVER A GIT PUSH: GitHub signs a `createCommitOnBranch` commit made with
# GITHUB_TOKEN, and the main ruleset requires signed commits (see release-please.yml, #577).
# A PR opened with GITHUB_TOKEN starts no workflows, so the checks are dispatched here.
#
# Needs: GH_TOKEN, GITHUB_REPOSITORY, gh, jq, git. HARNESSED_CMD overrides how harnessed runs.
set -euo pipefail
trap 'echo "pin-upgrade: failed: $BASH_COMMAND" >&2' ERR

repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}"
read -r -a harnessed <<< "${HARNESSED_CMD:-uv run --extra dev harnessed}"
day="$(date -u +%F)"
branch="upgrade-$day"
title="feat(catalog): upgrade pins $day"

# The same patterns as the `case` in live.yml job `changes`. tests/test_ci_pin_upgrade_workflow.py
# fails when the two differ.
LIVE_TRIGGERS=(
  'catalog/base/Dockerfile.harnessed-*'
  'catalog/base/harnessed-start'
  'src/harnessed/volumes.py'
  'src/harnessed/launcher.py'
  'src/harnessed/paths.py'
  '.github/workflows/live.yml'
)

prs() {
  gh pr list --repo "$repo" --head "$branch" --state "$1" --json number | jq length
}

# Decide 5 (GH-582): a PR for today already merged, so a second one would share its date.
if [ "$(prs merged)" -gt 0 ]; then
  echo "$branch already merged today; the next run picks up new bumps"
  exit 0
fi

if head="$(gh api "repos/$repo/git/ref/heads/$branch" 2>/dev/null | jq -er .object.sha)"; then
  git fetch --quiet origin "$branch"
  git checkout --quiet --detach "origin/$branch"
  on_remote=true
else
  head="$(git rev-parse HEAD)"
  on_remote=false
fi

"${harnessed[@]}" update --yes --no-rebuild < /dev/null

git add catalog mise.toml
if git diff --cached --quiet; then
  echo "no pin changed; nothing to do"
  exit 0
fi

# An API commit here carries additions only, so a deletion would vanish without a word.
deleted="$(git diff --cached --no-renames --name-only --diff-filter=D)"
if [ -n "$deleted" ]; then
  echo "pin-upgrade: refusing a deletion: ${deleted%%$'\n'*}" >&2
  exit 1
fi

changed="$(git diff --cached --no-renames --name-only)"
additions="$(
  while IFS= read -r f; do
    jq -n --arg path "$f" --arg contents "$(git show ":$f" | base64 -w0)" \
      '{path: $path, contents: $contents}'
  done <<< "$changed" | jq -s .
)"

payload="$(mktemp)"
trap 'rm -f "$payload"' EXIT
jq -n --arg repo "$repo" --arg branch "$branch" --arg oid "$head" --arg headline "$title" \
  --argjson additions "$additions" '{
    query: "mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid } } }",
    variables: {input: {
      branch: {repositoryNameWithOwner: $repo, branchName: $branch},
      expectedHeadOid: $oid,
      message: {headline: $headline},
      fileChanges: {additions: $additions}
    }}
  }' > "$payload"

if [ "$on_remote" = false ]; then
  gh api -X POST "repos/$repo/git/refs" -f "ref=refs/heads/$branch" -f "sha=$head" > /dev/null
fi
gh api graphql --input "$payload" | jq -er .data.createCommitOnBranch.commit.oid

if [ "$(prs open)" -eq 0 ]; then
  gh pr create --repo "$repo" --base main --head "$branch" --title "$title" \
    --body "Automated pin upgrade for $day (\`harnessed update --yes --no-rebuild\`). Opened by .github/workflows/pin-upgrade.yml."
fi

gh workflow run test.yml --repo "$repo" --ref "$branch"
live=false
while IFS= read -r f; do
  for pattern in "${LIVE_TRIGGERS[@]}"; do
    # shellcheck disable=SC2254  # the pattern is a glob on purpose, as in live.yml's case.
    case "$f" in $pattern) live=true ;; esac
  done
done <<< "$changed"
if [ "$live" = true ]; then
  gh workflow run live.yml --repo "$repo" --ref "$branch"
fi
