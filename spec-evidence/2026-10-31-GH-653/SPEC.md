# SPEC — `use` runs install scripts in the stack mise environment

## Summary
What it achieves: `harnessed use claude --global --stack se-ghissues` completes. Today it stops at the context-mode install with "mise reports no install root for npm:context-mode".

Why: `use` runs each recipe's install script with the user's own mise environment. The stack's `tools:` are installed into the stack's mise tree, so an install script that asks mise about a stack tool (context-mode's `mise where npm:context-mode`) finds nothing. `host-run` avoids this by pointing the process at the stack's mise tree before its installs run.

What changes: `use` sets the same stack mise environment and tool `PATH` that `host-run` sets, around the tool install, the plugin emit and the install scripts. It then puts the user's own values back before it calls `claude plugin`. The change is one block in the `use` command in `src/harnessed/launcher.py`, plus tests.

The criteria in plain words:
- S1: an install script run by `use` sees the stack's mise variables and the stack tool dirs at the front of `PATH`.
- S2: after that step, the user's mise variables and `PATH` are back as they were, including when an install fails, and every `claude plugin` call runs with the user's values.

What must not change: `host-run`, `container-run` and `assemble()` behave as before. The four mise helpers in `hostrun.py` keep their signatures and bodies. Every existing `use` test still passes.

How each criterion is proven: pytest tests through the `use` command, with a fixture recipe whose install script writes its environment to a file and a fake `claude` that records its environment. The engineer then reruns the command from the issue by hand.

Open decisions: none.

## Orientation
- Change: `use` applies the stack mise environment and tool `PATH` around its tool install, emit and install scripts, and restores the user's values before any `claude plugin` call.
- Why: install scripts that ask mise about a stack tool fail under `use`, because they see the user's mise, not the stack's.
- Lane: engineering, because it is a defect in the `use` verb that GH-649 added, found by the engineer running it, with no product author.
- Touches: `src/harnessed/launcher.py` (the `use` command), `tests/test_use.py`.
- Decide: none.

- Tier: 2 — a bug fix in one command.
- Issue: GH-653
- Isolation: worktree — `worktrees/use-install-mise-env`, branch `use-install-mise-env`, per AGENTS.md §Git workflow.

Terms used below:
- The stack mise variables are the keys and values of `hostrun._host_mise_env(<stack>)`, and the mise session variables are `hostrun._MISE_SESSION_VARS` (`MISE_DATA_DIR`, `MISE_CONFIG_DIR`, `MISE_TRUSTED_CONFIG_PATHS`, `MISE_STATE_DIR`).
- The stack tool prefix is `hostrun._stack_tool_path_prefix(<stack>)`, the entries `hostrun._apply_host_tool_path` puts at the front of `PATH`.
- The user's values are the mise session variables and `PATH` as they were when `use` started, with unset kept as unset.
- The rollback is the `except BaseException` block in `use` that wraps `plugin.emit_plugin` and `_host_run_installs`. When either raises, it removes the half-built plugin, moves the previous plugin back from `<mkt>/.prev/<stack>`, and rewrites `marketplace.json` (GH-649 agent decision A12). The restore of the user's values runs after the rollback, in a `finally` that encloses `_host_install_tools`, the emit, the installs and the rollback. harnessed makes no `claude plugin` call inside the `finally`; every one comes after it.

## Scenarios
### S1. Install scripts see the stack mise environment
- S1.1 Given a fixture recipe whose install script writes `env` to `$PROJECT_DIR/install-env.txt`, and a user environment with `MISE_DATA_DIR=/user/mise-data`, when `harnessed use claude <proj> --stack <that stack>` runs, then the file records every key of the stack mise variables with its value from `hostrun._host_mise_env(<stack>)`, and does not record `MISE_DATA_DIR=/user/mise-data`.
- S1.2 Given the same fixture, when `use` runs, then the recorded `PATH` begins with the stack tool prefix joined by `:`.
- S1.3 (boundary) Given a user environment with no mise session variable set, when `use` runs, then the install script still records each stack mise variable.

### S2. The user's values come back
- S2.1 Given a user environment with `MISE_DATA_DIR=/user/mise-data`, `MISE_STATE_DIR=/user/mise-state` and a known `PATH`, when `use` completes, then `os.environ` holds those three values again, and each other mise session variable that was unset is unset.
- S2.2 Given that environment and a fake `claude` that records its environment, when `use` runs, then every recorded `claude plugin` call has `MISE_DATA_DIR=/user/mise-data`, `MISE_STATE_DIR=/user/mise-state` and the known `PATH` with the fake's bin dir at its front.
- S2.3 (negative) Given an install script that exits 1, when `use` runs, then `use` exits nonzero and `os.environ` holds the user's values, as in S2.1.

## Must NOT
- `_launch_host`, `host-run`, `container-run` and `assemble()` change. (existing suite at the baseline count)
- `hostrun._apply_host_tool_path`, `_apply_host_mise_env`, `_snapshot_user_mise_env`, `_restore_user_mise_env` and `_host_mise_env` change. (diff shows no line in `hostrun.py`)
- An existing `use` test changes its assertions. (diff of `tests/test_use.py` adds tests only)
- A `claude plugin` call runs with the stack mise variables. (S2.2)
- A new dependency.

## Touches
- `src/harnessed/launcher.py`: in `use`, snapshot the user's values, apply the stack mise variables before `_host_install_tools` (the tool prefix comes from `_host_install_tools` and `_host_run_installs`, decisions.md Revision 2), and restore the user's values in a `finally` that runs after `_host_run_installs` and after the rollback (Terms).
- `tests/test_use.py`: S1 and S2, with an inline recipe whose install script writes its environment, and an extension of the fake `claude` that records its environment.

## Documentation
None, because #651 documents `use` and this change adds no flag and no message.

## Known limits
- `use` still runs no recipe `setup:` or `init:` script. #651 holds that question.
- No test runs the real context-mode install, because it needs the npm package from the registry. The engineer reruns the issue's command by hand.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | behavior regressions and S1-S2 | `tools/run-tests.sh` passes; count is the baseline plus the new tests |
| coverage | untested branches | `--cov-fail-under=80` passes |
| types | type errors | pyright reports no new error in `launcher.py` |
| lint | style and bug patterns | `ruff check src tests tools` exits 0 |
| shellcheck | shell defects | exits 0 |
| secrets | committed credentials | `gitleaks detect` finds nothing |
| live CI | the container path, since `launcher.py` is a live trigger | `live` and `live-docker` green on the PR |
| adversary | defects a self-review misses | every finding fixed or answered |
| manual | the issue's command | `harnessed use claude --global --stack se-ghissues` exits 0 and `<mkt>/plugins/se-ghissues/skills` holds the context-mode skills |
