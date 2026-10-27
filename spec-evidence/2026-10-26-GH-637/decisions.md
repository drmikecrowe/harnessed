# Decisions — keep the host Claude login refreshed when the refresher starts from an isolated tree

## Setup plan
- Isolation: worktree — `worktrees/GH-637-token-refresh` on branch `GH-637-token-refresh`; AGENTS.md forbids work on `main`.
- Git: signed commits on the branch; one commit per loop step that `/spec-evidence:build` names.
- New dependencies: none (`hypothesis` and `mutmut` are already declared in `pyproject.toml`).
- New files: none outside this story directory.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage, types, lint, shellcheck and secrets, and all six run. Mutation (`mutmut`, declared) and property (`hypothesis`, declared) run by hand for Tier 3. shellcheck does not apply: no shell file changes.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `pr-title.yml`, `live.yml`. `live.yml` does not trigger: no file in its trigger list changes.

## Facts this SPEC rests on
1. `_is_harnessed_owned` checks only `path.resolve()` against `paths.host_homes_root().resolve()` — read at `src/harnessed/hosthome.py:692-704`.
2. `host_homes_root()` is `xdg_data_home() / "harnessed" / "home"`, and `xdg_data_home()` follows `XDG_DATA_HOME` — read at `src/harnessed/paths.py:308-311` and `579-581`.
3. `host_store()` is `_host_claude_source() / ".credentials.json"`, and `_host_claude_source()` is `_host_claude_config_override() or ~/.claude` — read at `claudeauth.py:61-63` and `hosthome.py:338-378`.
4. `_lock_path`, `_log_path`, `_views_lock` and `pod_view_path` all sit under `_state_root()`, which follows `XDG_STATE_HOME` — read at `claudeauth.py:66-72`, `157-166`, `259-264`.
5. `_host_home_lock` creates the sibling file `<home.name>.lock` beside every host stack home, and the stamp is `.harnessed-stack` inside it — read at `hosthome.py:54` and `89-112`.
6. The real stack home `~/.local/share/harnessed/home/gortex-ghissues/claude` has both a `.harnessed-stack` file and a sibling `claude.lock` — `ls -la`, 2026-10-27.
7. `_invalidate_host_home` deletes the stamp by design, so containment must stay — docstring at `hosthome.py:360-363`.
8. The only callers of `_is_harnessed_owned` are `_host_claude_config_override` and `_host_omp_source` — Gortex `relations usages`.
9. Tests that pin the override: `TestHostClaudeSource` in `tests/test_launch_host.py:281-310`. None of them creates a marker, so all four still hold after the change — read.
10. No repo doc or wiki page names `claude-auth-refresher` — `rg` over the worktree and `main/docs`.

## Decide calls

### Decide 1. Where do the refresher lock and log live?
Evidence: `claudeauth.py:259-264` puts both under `_state_root()`, which follows `XDG_STATE_HOME`, while the views it syncs follow `XDG_DATA_HOME` (`claudeauth.py:169-174`).

- A. Under the data root: `paths.host_homes_root().parent / "claude-auth-refresher.lock"` (and `.log`), that is `$XDG_DATA_HOME/harnessed/`. Cost: the files leave the XDG state dir, against the usual split of state and data.
- B. Under the state root, with a short hash of the resolved `host_homes_root()` in the name, for example `claude-auth-refresher-<hash>.lock`. Cost: an opaque name, and an old unhashed lock file stays behind on every machine.

Default: A.
- Ruling: A (mcrowe, 2026-10-27)
Changes: S2.1 states the data-root paths with the ruling; the Orientation's `Decided:` line names it; the Summary lists no open decision.

## Revisions
### Revision 1. Decide 1 ruled A
The lock and log live under `$XDG_DATA_HOME/harnessed/`.
### Revision 2. Gate 1a round 1 findings applied
The Summary and Orientation state the lock ruling in plain words; the Decide line names the two settled risks and points at Known limits; Known limits gives the reason the sibling lock is a marker; S3.1 and S3.2 define the data root and how no refresh is due.
