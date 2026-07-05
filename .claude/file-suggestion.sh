#!/usr/bin/env bash
# Custom @ file-suggestion source. Claude Code sends JSON ({"query": "..."}) on stdin, not a raw
# string — must extract .query with jq, not pass the JSON blob straight to rg as a regex.
#
# docs/ is listed in .gitignore (it's an unpinned wiki clone, see .gitignore's own comment) so
# `rg --files` on the project root silently excludes it; re-scan it separately with
# --no-ignore-vcs so its contents still surface in @ suggestions.
query=$(cat | jq -r '.query')
root="${CLAUDE_PROJECT_DIR:-.}"
cd "$root" || exit 1
{ rg --files .; rg --files --no-ignore-vcs ./docs; } | sed 's#^\./##' | rg -i -- "$query" | head -15
