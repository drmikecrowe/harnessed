# Work Tracking: GitHub Issues

Durable work lives in **GitHub Issues**, not a local tracker. TodoWrite is for steps within this
session; an issue is for anything that outlives it. Both are fine — they do different jobs. Neither
overrides the other.

The ready queue and your assigned issues are already injected at session start by this recipe's
SessionStart hook. Do not run `prime.sh` yourself; it has already run.

- **Find work**: `~/.claude/skills/gh-issue-tracker/scripts/ready.sh` — open, unblocked, unclaimed.
  Do not hand-roll this query. `blockedBy` is a connection object (`{nodes, totalCount}`), not an
  array, and getting it wrong reports blocked work as ready.
- **Claim before starting**: `gh issue edit <n> --add-assignee @me`.
- **Relationships are native flags** on create and edit: `--parent` (containment: a sub-issue of an
  epic), `--blocked-by` / `--blocking` (ordering). They exist as of gh 2.94.0. Never write
  `Blocked by: #12` into an issue body — that is a mention, not a relationship, and nothing can
  query it. Note `gh issue edit` uses `--parent`, not `--set-parent`.
- **Amend a spec by posting a comment**, not by editing the issue body. Body edits have no
  conditional-write support and silently clobber concurrent writers.
- **Close via the PR**: put `Fixes <owner>/<repo>#<n>` in the PR body so GitHub records the causal
  link. Closing an issue unblocks whatever it was blocking, so re-run `ready.sh` afterwards to
  see what that surfaced.

Models frequently believe GitHub has no native blocking relationship. That was true before August
2025 and is wrong now. Trust the flags, not recall.

The `gh-issue-tracker` skill has the full command surface, triage queries, and the bulk-migration
procedure. This rule is only the always-on floor.
