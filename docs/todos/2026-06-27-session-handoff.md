# Session handoff — TIER 0 + container/worktree mounting

**Date:** 2026-06-27 · **Read this first when resuming after a re-mount.**

## Why this file exists
This Claude Code container had only `harnessed/main` mounted, but the worktree's git dir
lives in the sibling `harnessed/.bare/` (not mounted). The agent could **edit files** (shared
working tree) but **could not run git** (object store unreachable → "not a git repository").
Re-mount so `.bare` is reachable (see *Mounting* below) and git works normally.

## State of the TIER 0 work (CI + settings.json merge)
All files written and verified on disk. **Not yet committed** (git was unreachable in-container).
Hermetic suite green: `uv run --extra dev pytest` → **114 passed, 6 skipped**.

| File | Change |
|------|--------|
| `.github/workflows/test.yml` | NEW — hermetic pytest CI (PR + push to main, py3.12, no podman, no paths filter) |
| `src/harnessed/emit.py` | MOD — `required_settings`, `read_baked_settings`, `merge_settings`; `write_settings_json` delegates to `required_settings` |
| `src/harnessed/launcher.py` | MOD — `from . import emit`; `_merge_baked_settings` (UNCONDITIONAL post-build); call site after `_merge_baked_extensions` |
| `tests/test_emit.py` | MOD — 15 new unit tests (merge matrix incl. regression proof, deny-conflict, dedup, read/required) |
| `tests/test_recipes_integration.py` | MOD — 2 podman-gated tests exercising the real `create`/`cp` extraction |
| `docs/todos/2026-06-27-tier0-implementation-plan.md` | NEW — the decided build spec |
| `docs/todos/2026-06-27-unify-postbuild-podman-passes.md` | NEW — deferred perf TODO |
| `docs/todos/2026-06-27-session-handoff.md` | NEW — this file (optional to commit / can .gitignore) |

`roadmap-triage.md` and `non-urgent-nice-to-haves.md` are **yours**, not authored this session —
commit them separately if/when you want.

## Next actions (in order)
1. **Commit — two commits, CI first** (per the CI-first sequencing decision):
   ```bash
   # Commit 1 — CI
   git add .github/workflows/test.yml
   git commit -m "ci: add hermetic pytest workflow

   Runs uv run --extra dev pytest on PR + push to main, Python 3.12, no podman
   (HARNESSED_PODMAN integration tests skip). No paths filter so it can be a
   required status check without deadlocking PRs that don't touch src/tests.

   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"

   # Commit 2 — settings.json merge + tests + docs
   git add src/harnessed/emit.py src/harnessed/launcher.py \
           tests/test_emit.py tests/test_recipes_integration.py \
           docs/todos/2026-06-27-tier0-implementation-plan.md \
           docs/todos/2026-06-27-unify-postbuild-podman-passes.md
   git commit -m "fix: merge installer-written settings.json post-build instead of clobbering

   settings.json was generated from scratch at assemble time and mounted :ro over
   the container's, masking hooks/permissions a recipe or base image installed.
   Now resolved post-build via emit.merge_settings (union the required mcp__hatago
   grant into the baked file), keeping the assemble-time stub as the no-bake floor.
   Runs unconditionally so base-image settings are caught too.

   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
   ```
2. **Branch protection (manual, repo settings):** after the CI PR merges and the workflow has run
   once, add **`pytest`** as a required status check on `main` (the check name = the job name).
3. **Live integration run** on a podman host:
   `HARNESSED_PODMAN=1 uv run --extra dev pytest tests/test_recipes_integration.py -k merge_baked_settings`
4. **Roadmap next:** resolve the **persist scope-key** decision (Decision #2 in
   `roadmap-triage.md`) — per-project `sha1(project_path)` vs global `~/.local/share/harnessed/...`.
   It gates the persist work that the context/memory recipes need. Design call, not code yet.

## Mounting (the standard, kept)
Layout stays: `harnessed/.bare` (bare repo) + `harnessed/main` + feature worktrees.

To run an agent container against a worktree, the git **common dir must be mounted too**, because
a linked worktree is not self-contained (objects/refs live in `.bare`). Mount EITHER:
- the parent `harnessed/` (simplest; container sees all worktrees), OR
- `harnessed/main` **and** `harnessed/.bare` (narrower; only the one worktree),

…each at its **matching absolute path** (path-mirroring).

## Open design question (harnessed product) — RESOLVED: a launch flag IS needed
The container's entrypoint **auto-launches the agent** — there is no human `cd`. With the mount
root holding several worktrees, the launcher cannot infer which one this container is for, so the
working dir must be passed in. Two concepts that used to be one have split:

- **mount set** = worktree + its git common dir (`.bare`) — fix on the launcher's mount side.
- **agent working dir** = which worktree the entrypoint `cd`s into before launching the agent —
  needs an explicit flag (call it `--agent-dir` / `--workdir` / `--worktree`).

Design decisions to make:
1. **Default = cwd, required for auto-launch.** Interactive/host runs keep `workdir = cwd`; the
   container-driven launch passes the flag.
2. **Let the flag carry a path, not just a name.** A full mirrored path (`/abs/harnessed/main`)
   lets the launcher derive `git --git-common-dir` → `.bare` and mount it automatically, so ONE
   value yields both cwd and the extra mount. Accept a bare name (`main`) as "relative to mount
   root" for the simple manual-mount case.
3. **Naming:** avoid `--agent-dir` — `agent` already means the harness (claude/omp/opencode) in
   harnessed vocab; `--workdir` / `--cwd` / `--worktree` are unambiguous.

→ Candidate TODOs: (a) add the `--workdir`/`--agent-dir` flag (default cwd) flowing to the
container entrypoint as the agent's start dir; (b) teach `launcher._build_mount_args` to detect a
linked worktree (`git --git-dir` ≠ `--git-common-dir`) and bind-mount the common dir,
path-mirrored.
