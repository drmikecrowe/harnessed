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

default=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)
default=${default#origin/}
[ -n "$default" ] || default=$(git config --get init.defaultBranch 2>/dev/null) || default=main

case "$branch" in
"$default" | main | master) exit 0 ;;
esac

printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"feature branch '"$branch"' — not the protected default branch"}}'
