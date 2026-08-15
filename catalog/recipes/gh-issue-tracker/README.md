# gh-issue-tracker

Issue tracking over GitHub Issues: a skill for the operations, a SessionStart hook for live queue
state, and a pinned `gh` + `jq`.

Split out of `mikes-universal-setup` on 2026-08-08, where it lived as `skills/gh-issues`.

## Why it is its own recipe

`mikes-universal-setup` is a baseline of always-on **rules** — coding stance, tool preferences,
confirmation gates. This is not that. It is not universal (it needs a GitHub repo, an authenticated
`gh`, and a team that actually tracks work in Issues) and it is not passive: it ships a hook that
fires every session, a CLI, an egress allowance, and a credential mount. A rules baseline should
not drag that behind it for a project that tracks work somewhere else.

## What it ships

| Piece | Path | Notes |
| --- | --- | --- |
| Skill | `skills/gh-issue-tracker/SKILL.md` | Progressive disclosure — only the description sits in context until the model recognizes a backlog task. |
| Ready queue | `skills/gh-issue-tracker/scripts/ready.sh` | Open, unblocked, unclaimed. GitHub can filter *for* blocked issues but has no native unblocked query, so this is computed. |
| Claims | `skills/gh-issue-tracker/scripts/claim.sh` | Expiring machine-local claim files (default 2h) for concurrent agents on one host. Advisory; does not coordinate across machines. |
| Prime hook | `skills/gh-issue-tracker/scripts/prime.sh` | SessionStart. Reports how many issues are ready and what is assigned to you. |
| Wiring notes | `WIRING.md` | Authoring notes: per-harness wiring and design rationale. Recipe root, **not** under `skills/` — it is guidance for whoever maintains this recipe, and everything under `skills/` is copied into the assembled profile and spends agent context on every session. Its instructions are already realized in `recipe.yaml` (the SessionStart hook) and `install.sh`. |

## The skill and the hook both exist on purpose

They answer different questions. The skill is static text that loads on demand — good for "how do I
express a blocked-by relationship". The hook runs a query — it is the only one that can say *12
issues are ready and 2 are assigned to you*. Neither substitutes for the other, and they do not
conflict.

## Auth

Referenced, never replicated. The recipe bind-mounts the real host `~/.config/gh` and points `gh` at
the mirrored path via `GH_CONFIG_DIR`; no token is baked into an image or copied into a per-stack
home. This requires the expanded path in `~/.config/harnessed/persist-allowlist` — the launch fails
and names the exact line to add otherwise. Same shape as the `pulumi` recipe.

## The gh floor is load-bearing

`gh >= 2.94.0` (June 2026) is where `--parent`, `--blocked-by`, `--blocking` and the
`blockedBy`/`parent`/`subIssues` JSON fields landed. Below that version the skill does not fail — it
degrades into writing `Blocked by: #12` prose into issue bodies, which looks correct and is
unqueryable. `install.sh` rejects an old `gh` at build time rather than letting that surface weeks
into a backlog.

Models frequently believe GitHub has no native blocking relationship. That was true before August
2025 and is wrong now.

## Provenance

Authored here. Repo resolution, the expiring claim-file pattern, and the duplicate-work checks are
adapted from `skills/gh-issues/SKILL.md` in [openclaw/openclaw](https://github.com/openclaw/openclaw),
MIT licensed, Copyright (c) 2026 OpenClaw Foundation. Attribution is carried in the skill's own
Attribution section.

## Invariants

Four things this recipe must keep true. Each is cheap to break and expensive to notice.

- **The skill directory name and its frontmatter `name:` must match.** The *directory* name is what
  reaches `~/.claude/skills/<name>`, so a disagreement between the two is invisible in the source
  and wrong in every assembled profile.
- **`ready.sh` and `claim.sh` must agree on the state dir** (`GH_ISSUE_TRACKER_STATE_DIR`, default
  `~/.local/state/gh-issue-tracker`). If they disagree, claims land where the ready query cannot see
  them and every claimed issue reads as available. Claims are advisory and expire after 2h.
- **The parent flag is `--parent`.** `--set-parent` does not exist in `gh`; an example using it
  looks plausible and fails when run.
- **Scripts ship mode 0755.** A script vendored 0600 arrives 0600 in the assembled profile and dies
  with "permission denied" at the point of use, not at build. `install.sh` re-applies the bit, so
  the recipe is correct regardless of how the copy step behaves.
