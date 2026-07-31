#!/usr/bin/env bash
# Auto-approve push / PR creation ONLY when HEAD is not the repo's default branch.
#
# NOT keyed on $PWD (three worktree locations, and globs rot) and NOT on
# git-dir != git-common-dir — in a bare+main layout `main/` is ITSELF a linked
# worktree, so that test green-lights the canonical checkout. The branch is the
# invariant: task worktrees are on feature branches, main/ is on main.
#
# Fails CLOSED: any lookup failure (detached HEAD, no origin) emits nothing and
# falls through to the normal permission prompt.
set -u
branch=$(git symbolic-ref --short HEAD 2>/dev/null) || exit 0
[ -n "$branch" ] || exit 0

# Resolve the protected branch. NO `|| default=main` fallback: on a repo whose default is `trunk`,
# assuming `main` would leave `trunk` unprotected and auto-approve a push straight to it. If we
# cannot determine what to protect, we do not get to approve anything.
default=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)
default=${default#origin/}
[ -n "$default" ] || default=$(git config --get init.defaultBranch 2>/dev/null)
[ -n "$default" ] || exit 0

case "$branch" in
"$default" | main | master) exit 0 ;;
esac

# Being on a feature branch does not mean the PUSH targets one: `git push origin HEAD:main` sends
# work to the protected branch from a perfectly innocent HEAD. Rather than half-parse refspecs,
# refuse to auto-approve any `git push` carrying a colon at all — that covers `a:b` refspecs and
# explicit `user@host:path` remotes alike, and the cost of a false positive is one ordinary
# permission prompt. Scoped to `git push`: `gh pr create` bodies contain colons routinely.
# The settings.json `if:` filter guarantees we are only invoked for a push or a PR create, so an
# unreadable payload (no jq, malformed JSON, no stdin) means we cannot check what this push targets
# — and an unverifiable push must not be auto-approved. Exit without a decision; the user gets an
# ordinary prompt, which is exactly the behaviour before this hook existed.
cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null) || cmd=""
[ -n "$cmd" ] || exit 0
case "$cmd" in
*"git push"*)
  case "$cmd" in
  *:*) exit 0 ;;
  esac
  ;;
esac

printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"feature branch '"$branch"' — not the protected default branch"}}'
