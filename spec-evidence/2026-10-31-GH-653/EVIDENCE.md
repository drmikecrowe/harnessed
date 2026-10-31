## Evidence Report — `use` runs install scripts in the stack mise environment (Tier 2)

## Summary
Delivered: `harnessed use` now runs recipe install scripts in the stack's mise environment, as `host-run` does, and puts the user's mise variables and `PATH` back before any `claude plugin` call. That is the fix for `harnessed use claude --global --stack se-ghissues`, which stopped at context-mode's install with "mise reports no install root for npm:context-mode".

How each criterion was proven:
- S1, install scripts see the stack mise environment. Tests run `use` on a stack whose install script writes its own environment. They show every stack mise variable with the value `hostrun._host_mise_env` gives, the stack tool prefix at the front of `PATH`, and the same result when the user has no mise variables set. On the real se-ghissues tree, `mise where npm:context-mode` fails under the user's mise and resolves under the stack's (Process notes).
- S2, the user's values come back. Tests show the user's mise variables and `PATH` restored after a run and after a failed install, and every `claude plugin` call made with the user's values. A throwaway mutant that dropped the restore failed all three S2 tests.

Not proven: no local full gauntlet ran. On the engineer's ruling, tests, types, lint and shellcheck are left to the PR's CI, coverage is not run, and no baseline was recorded. The engineer's rerun of the issue's command is also still open.

## Agent decisions
<details><summary>3 agent decisions</summary>

### A1. `use` also restores `PATH`, not only the mise session variables
- Other option: restore the mise session variables only, as `_launch_host` does for the agent.
- Why: `use` calls `claude plugin` after the installs, and a `claude` reached through a mise shim breaks under a redirected `PATH` and mise environment (#449), so both go back.
- Command: hotfix

### A2. The redirect stays inline in `use`, not in a new shared helper
- Other option: move the snapshot, apply and restore into a helper in `hostrun.py` that `_launch_host` also calls.
- Why: `_launch_host` keeps the redirect for its whole launch and restores only the agent's copy, so the two lifetimes differ, and a shared helper would change `host-run`, which the Must NOT list forbids.
- Command: hotfix

### A3. `use` does not call `_apply_host_tool_path` itself
- Other option: call it before `_host_install_tools`, as `_launch_host` does.
- Why: `_host_install_tools` and `_host_run_installs` already put the prefix on the install scripts' `PATH`, a mutant without the call passed every test, and `_launch_host` needs its own call only for the MCP presence check, which `use` does not run at that point.
- Command: build

</details>

### Review risks
- No local full gauntlet ran (engineer's ruling O1). The suite, pyright, ruff and shellcheck run on the PR's CI, so this report cannot cite their results. The targeted run under Gauntlet covers the five test files nearest the change.
- Coverage at `--cov-fail-under=80` never ran, and nothing in CI runs it.
- No baseline stamp exists. The baseline was stopped at the engineer's ruling after its tests layer passed (337.4 s, exit 0, no count recorded), so a new failure in the full suite can only show up in CI.
- `_apply_host_mise_env` runs before the `try` that restores, so an exception raised inside it would leave a partial redirect (adversary round 1 hunch, not confirmed).
- `_restore_user_mise_env` drops a snapshot value that is itself a harnessed redirect, as it does for `host-run`. So `use` run inside another stack's host session ends with that variable unset, not restored (adversary round 1 hunch). S2 tests use plain user values only.

### Not reached by review
- Round 1: calls 3/10; hunts not reached: 1 (the layer commands were not compared with the merge-gate workflows), 2 (the call sites of `_host_install_tools` and `_host_run_installs` outside `use` were not listed), 8 (the diff has no EVIDENCE report to check), 9 (no names in the diff were checked for existence); sites not opened: /home/mcrowe/Programming/Personal/harnessed/worktrees/use-install-mise-env/src/harnessed/hostrun.py:456 (the body of `_host_install_tools` past line 483), /home/mcrowe/Programming/Personal/harnessed/worktrees/use-install-mise-env/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/worktrees/use-install-mise-env/.github/workflows/lint.yml, /home/mcrowe/Programming/Personal/harnessed/worktrees/use-install-mise-env/tools/gauntlet-layers.json

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: `use` applies the stack mise environment around its tool install, plugin emit and install scripts, and restores the user's mise variables and `PATH` before any `claude plugin` call.
- Proven: 6/6 scenarios mapped and passing
- Not proven: full suite, types, lint and shellcheck (SUBSTITUTED by the PR's CI); coverage (UNAVAILABLE, not run); baseline (not recorded); the manual rerun of the issue's command (UNAVAILABLE, engineer by hand)

- Process: spec-evidence 0.0.1 (gate files: story-gate.md none, spec-gate.md spec-evidence 0.0.1)
- Spec: spec-evidence/2026-10-31-GH-653/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit f194bd8)
- Intent review: not run, engineering lane
- Source state: commit 14af8c4 — the commit the targeted checks and the adversary read
- Baseline: none. Stopped after its tests layer, at the engineer's ruling.

<details>
<summary>Stamp: none, the gauntlet did not run (engineer's ruling O1)</summary>

No `gauntlet-stamp.json` exists for this story. The targeted checks below ran by hand at commit 14af8c4 on a clean tree.

</details>

### Spec → Test mapping
Every row is `pass`.

<details>
<summary>6/6 scenarios mapped and passing</summary>

| Scenario | Test | Status |
|---|---|---|
| S1.1 | tests/test_use.py::TestStackMiseEnv::test_s1_1_install_scripts_see_the_stack_mise_variables | pass |
| S1.2 | tests/test_use.py::TestStackMiseEnv::test_s1_2_install_path_begins_with_the_stack_tool_prefix | pass |
| S1.3 | tests/test_use.py::TestStackMiseEnv::test_s1_3_no_user_mise_variables_still_gives_the_stack_ones | pass |
| S2.1 | tests/test_use.py::TestStackMiseEnv::test_s2_1_the_user_values_come_back | pass |
| S2.2 | tests/test_use.py::TestStackMiseEnv::test_s2_2_every_claude_plugin_call_sees_the_user_values | pass |
| S2.3 | tests/test_use.py::TestStackMiseEnv::test_s2_3_a_failed_install_still_restores_the_user_values | pass |

</details>

Must NOT:
- `_launch_host`, `host-run`, `container-run` and `assemble()` are unchanged. The diff touches only the `use` command in `launcher.py`. The full suite runs on the PR's CI.
- The `hostrun.py` helpers are unchanged, because `hostrun.py` is not in the diff.
- Existing `use` assertions are unchanged. The `tests/test_use.py` diff adds tests and an `env` field to the fake `claude`'s record.
- No `claude plugin` call runs with the stack mise variables (S2.2).
- No new dependency: `pyproject.toml` and `uv.lock` are not in the diff.

### Gauntlet (final fresh run)
No row is `PASSED` from a gauntlet run. These are the targeted checks that ran by hand at 14af8c4:

<details>
<summary>0/6 manifest layers run as the gauntlet; 5 targeted checks run by hand</summary>

| Layer | Command | Status + result | Baseline | Selection | Log |
|---|---|---|---|---|---|
| tests | `tools/run-tests.sh tests/test_use.py tests/test_plugin.py tests/test_tools_field_parity.py tests/test_host_mise_trust.py tests/test_subprocess_timeout_audit.py -q` | SUBSTITUTED — 133 passed, 0 failed (5 files, not the suite) | none | targeted by hand | /tmp/gh653-tests.log |
| coverage | not run | UNAVAILABLE — not run, and no CI job runs it | none | skipped | none |
| types | pyright on `src/harnessed/launcher.py tests/test_use.py` | SUBSTITUTED — 0 errors (2 files, not the project) | none | targeted by hand | /tmp/gh653-pyright.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | SUBSTITUTED — All checks passed (by hand, not through the gauntlet) | none | full | /tmp/gh653-ruff.log |
| shellcheck | not run | SUBSTITUTED by CI's `lint` job (lint.yml:78). No shell file is in the diff. | none | skipped | none |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | SUBSTITUTED — no leaks found (by hand, not through the gauntlet) | none | full | /tmp/gh653-gitleaks.log |

</details>

### Layers not run as specified
- N-A: none
- UNAVAILABLE: coverage. It was not run, and no CI job runs a coverage threshold.
- UNAVAILABLE: live CI (`live`, `live-docker`) runs on the PR.
- UNAVAILABLE: the manual rerun of `harnessed use claude --global --stack se-ghissues`, which is the engineer's.
- SUBSTITUTED: tests. Five files ran instead of the suite. They cannot detect a regression in any other test file, which only CI's `pytest` and `pytest-py313` cover.
- SUBSTITUTED: types. pyright ran on two files instead of the project, which cannot detect a type error the change causes elsewhere. CI's `lint` job runs the project.
- SUBSTITUTED: lint and secrets. They ran by hand with the manifest's own commands, outside the gauntlet, so no stamp records them.
- SUBSTITUTED: shellcheck, by CI's `lint` job. No shell file is in the diff.

### Defect classes closed
- Generator: a host-side step that runs recipe code, in a process whose mise environment harnessed did not redirect to the stack. Enumerated by `rg -n '_host_run_installs\(|_host_run_setups\(|_host_run_inits\(' src/harnessed`. Sites: 4 call sites in 2 callers.
  - `use` (`launcher.py:3865`) is fixed.
  - `HostBackend.provision_tools` (`launcher.py:3014`, `3026`, `3029`) was already correct: `_launch_host` runs it after its redirect at `launcher.py:3352`.
- Generator: a mutation of `os.environ` inside `use` that is not undone before a `claude plugin` call. Sites: 2.
  - `_apply_host_mise_env` is fixed, restored in the `finally`.
  - The `PATH` rewrite by `_host_install_tools` (`hostrun.py:548`) is fixed, restored in the same `finally`.

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 153746/2294 |
| spec-evidence-intent | — | not run, engineering lane | unrecorded |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 201632/2650 |

### Process notes
- The engineer ruled O1: stop the baseline and the final gauntlet, and leave tests, types, lint and shellcheck to the PR's CI, because CI runs them with the same arguments.
- Real-tree check, run by hand. Under the user's mise, `mise where npm:context-mode` exited 1 with "npm:context-mode@1.0.169 not installed". With `_apply_host_mise_env(env, "se-ghissues")`, it exited 0 with `~/.local/share/harnessed/tools/se-ghissues/mise/installs/npm-context-mode/1.0.169`.
- Four of the six new tests passed before the fix, because nothing changed the environment for a stack with no `tools:`. A throwaway mutant with no restore failed S2.1, S2.2 and S2.3. A second mutant with no `_apply_host_tool_path` failed nothing, so the call was removed (A3, decisions.md Revision 2).
- Adversary round 1 had no findings and three hunches. The third hunch is already handled: `_host_install_tools`' only `os.environ` write is `PATH`, at `hostrun.py:548`, and the `finally` restores it. With no finding and no code change, round 2 did not run.
