# Decisions — `use` runs install scripts in the stack mise environment

## Setup plan
- Isolation: worktree — `worktrees/use-install-mise-env` on branch `use-install-mise-env`, from `origin/main` at 5e82960, as AGENTS.md §Git workflow requires.
- Git: signed commits on `use-install-mise-env`; one commit per RED/GREEN pair; PR to `main` at the end.
- New dependencies: none.
- New files: none. The fixture recipe is written inline in `tests/test_use.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage, types, lint, shellcheck and secrets, and all six run. No property or mutation layer is needed for a Tier 2 fix.
- Merge gate: `.github/workflows/test.yml` (pytest), `lint.yml` (ruff, pyright, shellcheck), `live.yml` (live and live-docker, triggered by `launcher.py`), `pr-title.yml`, and the `code-review` check — 7 checks transcribed.

## Facts this SPEC rests on
1. `catalog/recipes/context-mode/install.sh:39` runs `mise where npm:context-mode` and fails closed on an empty answer — read.
2. `_launch_host` calls `_apply_host_tool_path(os.environ, stack)` and then `_snapshot_user_mise_env` and `_apply_host_mise_env(os.environ, stack)` before its installs (`launcher.py:3340-3352`), and `_restore_user_mise_env` on the agent's env (`launcher.py:3455`) — read.
3. `use` calls `_host_install_tools` and `_host_run_installs` with neither (`launcher.py`, the `use` command) — read.
4. `_host_run_installs` builds each script's env from `dict(os.environ)` (`hostrun.py`, `_host_run_installs`) — read.
5. `_MISE_SESSION_VARS` is `MISE_DATA_DIR`, `MISE_CONFIG_DIR`, `MISE_TRUSTED_CONFIG_PATHS`, `MISE_STATE_DIR` (`hostrun.py:176`) — read.
6. The failing run's output shows the tools were installed into `~/.local/share/harnessed/tools/se-ghissues/mise` — the issue body, pasted by the engineer.

## Decide calls
none

## Revisions
### Revision 1. Gate 1a round 1 finding fixed
Defined the rollback in Terms, and placed the restore after it, in a `finally` that encloses the tool install, the emit, the installs and the rollback (PR-REFERENT 1). Said that harnessed makes no `claude plugin` call inside the `finally` (gap 2).
