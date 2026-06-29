# Session handoff — TIER 0 + container/worktree mounting — **CLOSED**

**Date:** 2026-06-27 · **Closed:** 2026-06-29. Kept as a decision record; the work below has landed.

## Outcome
All TIER 0 work is committed and verified. Hermetic suite green; the podman-gated settings
integration tests pass on a real podman host (`2 passed`).

| Item | Status |
|------|--------|
| CI — hermetic pytest workflow (`.github/workflows/test.yml`) | ✅ committed (`7d0add6`) |
| settings.json post-build merge (`emit.merge_settings` + `launcher._merge_baked_settings`) | ✅ committed (`bf09273`) |
| stopped-leftover recovery + `_run` error surfacing | ✅ committed (`2022a85`) |
| `--agent-start-folder` (agent start dir) | ✅ committed (`4d632b0`) |
| Branch protection — require the `pytest` check on `main` | ✅ done (repo settings) |
| Live integration run (`HARNESSED_PODMAN=1 … -k merge_baked_settings`) | ✅ 2 passed on a podman host |

The four TIER 0 commits were split out of one working tree via hunk-level staging so each is a single
logical change.

## Decision: worktree `.bare` auto-mount — **WON'T DO** (superseded)
The original "open design question" split two concepts: the **mount set** (worktree + its git common
dir `.bare`, needed so `git` works in-container for a *linked* worktree) and the **agent working dir**.

- The working-dir half shipped as `--agent-start-folder` (`_resolve_start_dir`): names a subfolder of
  the still-fully-mounted project; the entrypoint opens the agent there.
- The mount half — teaching `_build_mount_args` to detect a linked worktree
  (`git --git-dir` ≠ `--git-common-dir`) and auto-bind-mount `.bare`, path-mirrored — is **dropped**.
  Reachability of `.bare` is achieved by simply **mounting the parent `harnessed/` dir** (the
  handoff's "simplest" option) and pointing the agent at the worktree with `--agent-start-folder`.
  The auto-mount was only convenience; the flag + parent-mount cover the case without growing
  `_build_mount_args`.

## Still open (roadmap, never part of TIER 0)
**Persist scope-key** decision — per-project `sha1(project_path)` vs global
`~/.local/share/harnessed/…`. Gates the persist work the context/memory recipes need. Design call.

## Mounting reference (unchanged)
A linked worktree is not self-contained (objects/refs live in `.bare`). To run an agent container
against a worktree, mount EITHER the parent `harnessed/` (simplest; sees all worktrees) OR
`harnessed/main` **and** `harnessed/.bare` — each at its matching absolute path (path-mirroring).
