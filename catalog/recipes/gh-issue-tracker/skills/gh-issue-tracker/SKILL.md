---
name: gh-issue-tracker
description: Manage a GitHub Issues backlog with `gh`: find ready work, create issues with blocked-by dependencies and epic links, claim, close, triage. Use when asked what to work on next, what is blocked, or to groom or migrate a beads/bd backlog.
---

# gh-issue-tracker

Backlog management over GitHub Issues. This is a **tracking** skill: it finds,
files, links, claims, and closes work. It deliberately does not implement or
prescribe any development methodology — no PRDs, no specs, no acceptance
criteria, no definition-of-done, no required review gates. File issues however
you like; this skill only handles the tracking layer.

For issue-to-PR automation (spawning workers to fix issues and open PRs), see
the separate `gh-issues` skill from openclaw. This skill adapts its claim
handling from that one. The two compose: use this one to decide *what* is
workable, that one to actually *do* it.

## Requirements

- `gh` >= **2.94.0**. Two things landed in 2.94.0 (June 2026): the dependency
  and hierarchy flags (`--blocked-by`, `--blocking`, `--parent`), and the
  `blockedBy`/`blocking`/`parent`/`subIssues` JSON fields. Verify before
  trusting output:
  ```bash
  gh issue create --help | grep -E -- '--parent|--blocked-by|--blocking'
  ```
  If those flags are absent, tell the user to upgrade `gh`. Never fall back to
  writing "Blocked by: #12" in the issue body. That creates a mention, not a
  relationship, and nothing can query it.
- `jq`, and authentication via `gh auth status` or `GH_TOKEN`.

Models frequently believe GitHub has no native blocking relationship. That was
true before August 2025 and is wrong now. Trust the flags above, not recall.

## Resolve the repo first

```bash
gh repo view --json nameWithOwner,defaultBranchRef
```

Infer from the current repo unless the user names one. If `gh auth status`
fails and `GH_TOKEN` is unset, stop and ask for credentials rather than
producing empty lists that look like an empty backlog.

## What to work on next

Run the bundled script rather than assembling the query inline — it encodes
several failure modes that are easy to get wrong:

```bash
scripts/ready.sh                 # human-readable
scripts/ready.sh --json          # for programmatic use
scripts/ready.sh --label bug --limit 20
```

An issue is ready on four conditions. It is open. It has no OPEN blocker. No
open PR is set to close it. It carries no live local claim. GitHub filters *for*
blocked issues but has no native unblocked query. Hence the computation.

Two things the script gets right that hand-rolled versions usually don't. First,
`blockedBy` is a connection object shaped `{nodes: [...], totalCount: N}`, not a
plain array. Second, an unreadable blocker still counts as blocking. Reporting
blocked work as ready sends an agent at something it cannot finish, so the bias
runs the other way.

## Creating issues

Set relationships at creation time — retrofitting them later is where they get
forgotten:

```bash
gh issue create --title "Fix socket path resolution" \
  --body-file /tmp/body.md \
  --label bug --label P1 \
  --blocked-by 200,201 \
  --parent 42
```

Use `--body-file` rather than an inline multi-line string; quoting breaks in
ways that silently truncate the body.

**Choose the right relationship.** These are different and often confused:

- `--parent` (sub-issue): *containment*. The child is part of the epic. An epic
  with children is structural; an epic with none is decorative.
- `--blocked-by` / `--blocking`: *ordering*. This work cannot start until that
  work finishes.

Most epics want children, not blockers. If the user describes an epic and then
lists work "under" it, reach for `--parent`.

## Editing relationships

```bash
gh issue edit <n> --add-blocked-by 12 --remove-blocked-by 9
gh issue edit <n> --add-blocking 30
gh issue edit <n> --parent 42            # --remove-parent to detach
gh issue edit <n> --add-assignee @me --add-label in-progress
```

Verify after any relationship change, because a silent no-op looks identical to
success:

```bash
gh issue view <n> --json number,parent,subIssues,subIssuesSummary,blockedBy,blocking
```

## Claiming work

Durable ownership is the GitHub assignee. Use it for anything that will outlive
the session:

```bash
gh issue edit <n> --add-assignee @me
```

For short-lived coordination between concurrent agents on one machine, the
claim file is cheaper and self-healing. A crashed agent's claim expires rather
than wedging the issue permanently:

```bash
scripts/claim.sh take <n>
scripts/claim.sh release <n>
scripts/claim.sh list
```

Claims are advisory and machine-local; they do not coordinate across hosts.
`ready.sh` honors them. Default TTL is 2h (`GH_ISSUE_TRACKER_CLAIM_TTL`).

Release the claim when work finishes or fails. A claim left behind is invisible
for two hours, which reads to the user as "that issue vanished from the queue."

## Closing

```bash
gh issue close <n> --reason completed --comment "Fixed in #<pr>"
gh issue close <n> --reason "not planned" --comment "Superseded by #<m>"
```

Prefer letting a merged PR close the issue via `Fixes owner/repo#<n>` in the PR
body — that records the causal link. Closing an issue also unblocks anything it
was blocking, so re-running `ready.sh` after a close is how new work surfaces.

## Triage

Useful reads when grooming rather than executing:

```bash
# What is blocked, and by what
gh issue list --state open --json number,title,blockedBy \
  --jq '.[] | select((.blockedBy.totalCount // 0) > 0)
        | "#\(.number) \(.title) <- \([.blockedBy.nodes[].number] | tostring)"'

# Epics with no children (decorative epics)
gh issue list --state open --json number,title,subIssuesSummary \
  --jq '.[] | select((.subIssuesSummary.total // 0) == 0) | "#\(.number) \(.title)"'

# Distribution by label
gh issue list --state open --limit 300 --json labels \
  --jq '[.[].labels[].name] | group_by(.) | map({(.[0]): length}) | add'
```

When a backlog is filling faster than it drains, say so plainly and offer to
close or downgrade rather than silently listing everything. A ready queue that
returns 69 items is not usable as a queue.

## Bulk migration from a local tracker

When importing from beads/bd or similar, do it in two passes. Create every
issue first, recording the old-id → new-number mapping, then wire relationships
in a second pass. Dependencies frequently point at issues that do not exist yet
on the first pass, and a failed `--blocked-by` at creation time loses the whole
issue.

```bash
# pass 1: create, capture mapping
gh issue create --title "$T" --body-file "$B" --label "$L" --json number -q .number

# pass 2: relationships, once every number is known
gh issue edit "$NEW" --add-blocked-by "$MAPPED_BLOCKER"
```

Confirm the target repo with the user before a bulk create. Issues cannot be
bulk-deleted, so a misdirected import is expensive to undo — this is the one
step in this skill worth an explicit confirmation.

## Attribution

This skill adapts repo resolution, the expiring claim-file pattern, and the
duplicate-work checks from `skills/gh-issues/SKILL.md` in
[openclaw/openclaw](https://github.com/openclaw/openclaw), MIT licensed,
Copyright (c) 2026 OpenClaw Foundation.
