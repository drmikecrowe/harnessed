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
# Needs: GH_TOKEN, GITHUB_REPOSITORY, gh, jq, git. HARNESSED_CMD overrides how harnessed runs; it
# is split on whitespace only, with no shell quoting, so no single argument in it may hold a space.
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

open_prs() {
  gh pr list --repo "$repo" --head "$branch" --state open --json number | jq length
}

# Decide 5 (GH-582), widened by the PR #593 review: a PR for today was merged or closed. A second
# PR would share its date, and reopening one would overrule whoever closed it. `--state all` plus
# a filter on `state`, so this never rests on how gh maps the word "closed". Checked again just
# before the commit, because a person can merge or close during the long `update`.
stop_if_finished() {
  local finished
  finished="$(gh pr list --repo "$repo" --head "$branch" --state all --json state \
    | jq '[.[] | select(.state != "OPEN")] | length')"
  if [ "$finished" -gt 0 ]; then
    echo "$branch already closed or merged today; the next run picks up new bumps"
    exit 0
  fi
}
stop_if_finished

if head="$(gh api "repos/$repo/git/ref/heads/$branch" 2>/dev/null | jq -er .object.sha)"; then
  # Anonymous fetch: the workflow keeps no git credential (persist-credentials: false), so the
  # write token is never in git config while `update` runs third-party resolvers. That works only
  # because this repository is PUBLIC; a private fork must add a credential here.
  git fetch --quiet origin "$branch"
  git checkout --quiet --detach "origin/$branch"
  on_remote=true
else
  head="$(git rev-parse HEAD)"
  on_remote=false
fi

"${harnessed[@]}" update --yes --no-rebuild < /dev/null

git add catalog mise.toml
# `update` writes pins only under catalog/ and mise.toml. A tracked file changed anywhere else
# means that stopped being true, and committing part of its output is worse than failing
# (PR #593 review). Untracked files are left out: tooling on the runner may create some.
stray="$(git status --porcelain --untracked-files=no -- . ':!catalog' ':!mise.toml')"
if [ -n "$stray" ]; then
  echo "pin-upgrade: harnessed update changed files outside catalog/ and mise.toml:" >&2
  echo "$stray" >&2
  exit 1
fi
if git diff --cached --quiet; then
  echo "no pin changed; nothing to do"
  exit 0
fi

# An API commit here carries additions only, so a deletion would vanish without a word.
deleted="$(git diff --cached --no-renames --name-only --diff-filter=D)"
if [ -n "$deleted" ]; then
  while IFS= read -r f; do
    echo "pin-upgrade: refusing a deletion: $f" >&2
  done <<< "$deleted"
  exit 1
fi

changed="$(git diff --cached --no-renames --name-only)"

work="$(mktemp -d)"
created_ref=false
# A ref this run created and never committed to is removed on the way out, so a failed commit
# leaves no empty `upgrade-<date>` on main's sha (PR #593 review). Best effort: a failed delete
# must not hide the error that got us here, and the next run reuses the ref anyway (S3.4).
cleanup() {
  local sha
  rm -r "$work"
  # Only while the ref is still the bare one we made: a commit can land and its reply be lost,
  # and then the ref has moved and must survive (PR #593 review).
  if [ "$created_ref" = true ] \
    && sha="$(gh api "repos/$repo/git/ref/heads/$branch" 2>/dev/null | jq -er .object.sha)" \
    && [ "$sha" = "$head" ]; then
    gh api -X DELETE "repos/$repo/git/refs/heads/$branch" > /dev/null || true
  fi
}
trap cleanup EXIT

# File contents travel through files (--rawfile, --slurpfile), never argv: Linux caps one argument
# at 128 KiB, and a catalog-wide bump with a lockfile passes that as base64 (PR #593 review).
while IFS= read -r f; do
  git show ":$f" | base64 -w0 > "$work/blob"
  jq -n --arg path "$f" --rawfile contents "$work/blob" '{path: $path, contents: $contents}'
done <<< "$changed" | jq -s . > "$work/additions.json"

payload="$work/payload.json"
jq -n --arg repo "$repo" --arg branch "$branch" --arg oid "$head" --arg headline "$title" \
  --slurpfile additions "$work/additions.json" '{
    query: "mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid } } }",
    variables: {input: {
      branch: {repositoryNameWithOwner: $repo, branchName: $branch},
      expectedHeadOid: $oid,
      message: {headline: $headline},
      fileChanges: {additions: $additions[0]}
    }}
  }' > "$payload"

stop_if_finished
if [ "$on_remote" = false ]; then
  gh api -X POST "repos/$repo/git/refs" -f "ref=refs/heads/$branch" -f "sha=$head" > /dev/null
  created_ref=true
fi
gh api graphql --input "$payload" | jq -er .data.createCommitOnBranch.commit.oid
created_ref=false

if [ "$(open_prs)" -eq 0 ]; then
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
