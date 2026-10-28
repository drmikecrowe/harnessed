## Evidence Report — Integrations: one pattern for aoe, Zed, Atlas and VS Code, run with --register-<name>-only (Tier 3)

## Summary
Delivered: every global launcher now takes `--register-<name>-only`. The flag runs one executable `catalog/integrations/<name>/register`, overlay first, after it builds a missing or stale profile, and starts no agent. aoe moved onto this pattern, so a normal launch no longer writes an aoe row or a local launcher, and `--create-aoe-only` is gone. New Zed, Atlas and VS Code integrations edit their settings files through `harnessed.jsonc`, a standard-library editor that keeps every other byte. `host-run` reads the VS Code Claude Code wrapper call as passthrough. Why: registration was hard-coded for aoe, automatic on every launch, and manual for the three editors.

How each criterion is proven:
- AC-1 (aoe): tests of the shipped `register` script, the hidden `aoe-register` command and the runner (S1.1, S1.5 to S1.8). The second-run and pre-change-row clauses rest on the existing `sync_session` tests and on `test_aoe_real` against the real `aoe` binary (S1.2 to S1.4).
- AC-2 (Zed), AC-3 (Atlas), AC-4 (VS Code): tests that run the shipped scripts against a temporary home and compare the settings files byte for byte (S2, S3, S4.1 to S4.5, S4.7). Property tests and mutation testing cover the editor. For AC-4's panel clause, a child-process test calls the registered wrapper exactly as the extension does, and the stack's claude starts with the SDK arguments (S4.6).
- AC-5 (lookup), AC-6 (no automatic registration), AC-7 (build first): runner tests through `main` (S5, S6, S7.1 to S7.4). For AC-7's `initialize` clause, a test registers on a stack with no profile, which builds it, and the ACP launcher's `host-acp` then answers `initialize` with a `result` (S7.5).

Not proven: the editors' own UIs, which no test drives: the VS Code panel's own spawn, the Zed panel and the Atlas list. Those remain the user's manual checks. The `live` and `live-docker` jobs run only on the PR. Real execution is SUBSTITUTED. Mutation testing leaves 45 equivalent mutants, each named under "Layers not run as specified".

## Agent decisions
<details><summary>17 agent decisions</summary>

### A1. An integration is a directory with an executable file named `register`
- Other option: any single executable file in the directory, whatever its name.
- Why: a fixed marker name fits `_KIND_MARKER` and lets `find_in_catalog`/`list_catalog` serve the new kind unchanged.
- Command: plan

### A2. The container backend's Zed and Atlas key adds `, container`
- Other option: one key per harness and stack, so registering the container launcher replaces the host entry.
- Why: AC-2 and AC-3 name only the host key; a separate key keeps both entries instead of one silently replacing the other.
- Command: plan

### A3. The aoe integration refuses an ACP launcher
- Other option: map an ACP verb to the run verb of the same backend and register that.
- Why: an aoe row replays a terminal launcher, so a row from an ACP launcher would be a guess; refusing is one check and names the right launcher.
- Command: plan

### A4. Zed updates only `type` and `command` in an existing entry
- Other option: replace the whole entry value.
- Why: a user's entry can hold `default_config_options` (fact 13); replacing it would delete the user's settings.
- Command: plan

### A5. The launch's aoe options reach the aoe integration as `HARNESSED_AOE_*` variables
- Other option: pass the launch's remaining argv to `register` as arguments.
- Why: typer has already parsed those options; variables keep the integration's interface to names and values, the same as the other variables.
- Command: plan

### A6. One register flag per command
- Other option: run several integrations in order from one command.
- Why: the story names one flag per run, and one exit status per integration stays clear.
- Command: plan

### A7. The VS Code argv rule reads only the first positional token after the options
- Other option: drop the first absolute path to an executable `claude` found anywhere in argv.
- Why: the wrapper call puts it right after `--stack S`; reading one position cannot misread an option value elsewhere.
- Command: build

### A8. The Zed, VS Code and Atlas paths honour `XDG_CONFIG_HOME` and `XDG_DATA_HOME`
- Other option: the fixed `$HOME/.config` and `$HOME/.local/share` paths the scenarios name.
- Why: Zed, Electron and Tauri read those variables on Linux, and with them unset the paths are the scenarios' paths.
- Command: build

### A9. An optional contract name the parent set is removed unless this launch was given its flag
- Other option: pass the parent's value through unchanged.
- Why: a value an outer launch left in the environment would read as this launch's `--aoe-group`.
- Command: build

### A10. The JSON editor inserts a new member first in its object, at the start of its own line
- Other option: append it after the last member.
- Why: appending adds a comma to the line above, which S2.3 forbids; inserting first changes no existing line.
- Command: build

### A11. Zed and Atlas write with `setdefault` on the entry, then `set` on `type` and `command`
- Other option: one `merge` operation that writes the file once.
- Why: three single-value edits reuse one primitive; each write is atomic and a repeat run writes nothing.
- Command: build

### A12. A normal launch still passes the harness `--name <row title>` when aoe is usable
- Other option: drop the `--name` too, since a launch writes no row.
- Why: the Must NOT keeps every other launch behaviour; a row registered by `--register-aoe-only` still carries that title.
- Command: build

### A13. The JSON editor writes through a symlink to its target
- Other option: replace the link with a regular file, as a plain rename does.
- Why: dotfile managers link settings files, and replacing the link would silently detach the user's managed copy.
- Command: build

### A14. The local launcher `aoe-register` writes carries no `# as typed:` line
- Other option: pass the typed command line to `aoe-register` in another variable.
- Why: the line is display only, and a variable outside the contract would widen it for one comment.
- Command: build

### A15. The vscode integration registers `HARNESSED_RUN_LAUNCHER`, not `HARNESSED_LAUNCHER`
- Other option: register `HARNESSED_LAUNCHER`, the launcher the flag was given to.
- Why: from an ACP launcher that would set the wrapper to an ACP agent, which the extension cannot run.
- Command: build

### A16. A register run skips the claude imports prompt a `host-run` launch asks
- Other option: ask it, as a launch does.
- Why: no agent starts, and the agent-of-empires skill runs the flag from a script with no one to answer.
- Command: build

### A17. Only the aoe integration refuses a foreign file at the global launcher's name
- Other option: the runner refuses every integration when its own global launcher was not written.
- Why: aoe already refused it (S1.13); the editors name the launcher path, which the user may own on purpose.
- Command: build

</details>

### Review risks
- A build before a host register run needs a container runtime. S7.1 prescribes `_build_stack(rt, S, H)`, which runs `_preflight_runtime`. On a host-only machine with a missing or stale profile, `--register-*-only` on a host launcher fails, though `host-run` itself would assemble in-process (adversary round 2 hunch, confirmed at `src/harnessed/launcher.py` `_build_stack`).
- A17 in practice: with a foreign file at `~/.local/bin/harnessed-acp-claude-S-host`, `--register-zed-only` registers that path and exits 0. The runner prints the "global launcher not written" warning first (adversary round 1 finding 1).
- `_typed_invocation` in `src/harnessed/launcher.py` now has no caller (A14), and `aoe.sync_session`'s `background=True` path has none either. Seven comments in `src/harnessed/aoe.py` (lines 20, 73, 116, 749, 907, 916, 1032) still name `--create-aoe-only`. Both are named here and left as found; `aoe.py` is outside Touches.
- In a CRLF settings file, an inserted member's lines end in LF; replacing a value keeps CRLF (adversary round 2 hunch).
- A comment directly above an object's first member ends up above the new member inserted before it. No byte is lost (adversary round 1 hunch).
- On an ACP verb, a register flag placed after `--cli` is claude's argv and does not register (adversary round 2 hunch).
- S1.1, S1.5 and S1.6 stub `aoe.sync_session` at the `aoe-register` seam. The row semantics behind S1.2 to S1.4 come from tests that predate this change: the mocked `sync_session` tests, and `test_aoe_real`, which runs the real `aoe` binary on this machine but skips in CI.
- The settings paths are the Linux ones (A8). macOS keeps VS Code and Atlas settings under `~/Library/Application Support`, which no integration reads.
- Tests removed with the behaviour the SPEC removed: `TestCreateAoeOnly`'s two passive-mirror tests and its drift-and-continue test (AC-6), and `TestHookPlacement` (two tests), whose property S7.1 and S7.4 now pin. `TestHostRunLeavesNothingBehind`'s two persistence tests now assert that nothing is written (AC-6). `tests/test_launch_host.py`, listed in Touches, needed no change and passes as it was.

### Not reached by review
- Round 1: calls 4/10; hunts not reached: 1 (the layer commands vs test.yml, lint.yml and live.yml argument lists were not compared), 8 (no EVIDENCE report in the diff), 9 (not checked: paths.find_in_catalog's behaviour on a missing name, or that `python -m harnessed` dispatches `aoe-register` through launcher.main), 10 (SPEC has a Documentation section, so no finding); sites not opened: src/harnessed/launcher.py:3760 (host_acp body above the register block), src/harnessed/launcher.py:4505 (container_run ordering of the register block vs _require_supported_harness), src/harnessed/launcher.py _runtime and _build_stack, src/harnessed/paths.py find_in_catalog and list_catalog, tests/test_launch_host.py (SPEC lists it as touched; it is not in the diff), every caller of `_persist_this_launch`, `_write_global_launchers` and `_session_name_args` outside the diff hunks
- Round 2: calls 5/10; hunts not reached: 1 (the layer commands and the CI shellcheck/pyright/ruff argument lists were not compared with the workflow files), 7, 8 (no EVIDENCE report in the diff), 9 (pyproject package-data and the exec bit surviving the wheel were not verified); sites not opened: /home/mcrowe/Programming/Personal/harnessed/GH-569-plugin-support/src/harnessed/launcher.py:833 (rest of _build_stack), /home/mcrowe/Programming/Personal/harnessed/GH-569-plugin-support/src/harnessed/paths.py:415-540 (find_in_catalog and list_catalog behaviour for a missing integration), /home/mcrowe/Programming/Personal/harnessed/GH-569-plugin-support/src/harnessed/launchscript.py (write() default argv), /home/mcrowe/Programming/Personal/harnessed/GH-569-plugin-support/.github/workflows/lint.yml and test.yml

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: `--register-<name>-only` on every global launcher runs a catalog integration after a build-if-needed; aoe, Zed, Atlas and VS Code ship as integrations, and a launch registers nothing.
- Proven: 51/52 scenarios mapped and passing; 1 unverified (the manual layer: the VS Code, Zed and Atlas UIs).
- Not proven: the editors' UIs (manual, the user's); live layer (runs on the PR); real execution SUBSTITUTED; mutation testing with 45 named equivalent mutants.

- Process: spec-evidence 0.16.2
- Spec: spec-evidence/2026-10-27-GH-569/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit e49e2ec, `GH-569: spec approved`)
- Intent review: round 1 changed S1.3, S1.4, S4.7, S5.8 and Known limits; round 2 changed the Summary (the no-`src/` rule governs later integrations), S1.4 (rename-and-add is the AC-1 repair) and S4.4 (cites the extension source for the wrapper argv)
- Source state: commit 8687ad28c0a62373ebe8268ae3235a5a70f75f0b, the commit the final run read. Adversary round 2 read fc32ac1; every commit after it changes tests and spec-evidence files only, no file under `src/` or `catalog/`.
- Baseline: baseline-stamp.json at commit e49e2ec0459b43deacfebc2a062fb57d1a3abc4e, green (4606 passed, 79 skipped)

<details>
<summary>Stamp: green, 6/6 layers</summary>

```json
{
  "result": "green",
  "mode": "full",
  "expected_layers": [
    "tests",
    "coverage",
    "types",
    "lint",
    "shellcheck",
    "secrets"
  ],
  "completed_layers": [
    "tests",
    "coverage",
    "types",
    "lint",
    "shellcheck",
    "secrets"
  ],
  "layer_seconds": {
    "tests": 290.863,
    "coverage": 354.013,
    "types": 13.237,
    "lint": 0.111,
    "shellcheck": 2.521,
    "secrets": 3.3
  },
  "layers": {
    "tests": {
      "baseline": "reused",
      "selection": "off"
    },
    "coverage": {
      "baseline": "reused",
      "selection": "off"
    },
    "types": {
      "baseline": "reused",
      "selection": "off"
    },
    "lint": {
      "baseline": "reused",
      "selection": "off"
    },
    "shellcheck": {
      "baseline": "reused",
      "selection": "off"
    },
    "secrets": {
      "baseline": "reused",
      "selection": "off"
    }
  },
  "failed": null,
  "exit_code": 0,
  "commit": "8687ad28c0a62373ebe8268ae3235a5a70f75f0b",
  "dirty": false,
  "written": "2026-10-27T14:38:06.192Z"
}
```

</details>

### Spec → Test mapping
Row not `pass`: the manual layer, unverified — the VS Code panel's own spawn, the Zed panel and the Atlas list, which no test can drive.

Test ids below are relative to `tests/`. `ti` is `test_integrations.py`; `tj` is `test_jsonc.py`.

<details>
<summary>51/52 scenarios mapped and passing</summary>

| Scenario | Test | Status |
|---|---|---|
| S1.1 | ti::TestAoeRegister::test_s1_1_one_row_and_the_local_launcher; ti::TestAoeScript::test_the_script_hands_over_to_aoe_register | pass |
| S1.2 (boundary) | test_aoe.py::TestWriteDispatch::test_already_registered_is_success_without_writing; test_aoe_real.py::test_relaunching_after_a_repair_converges | pass |
| S1.3 (boundary) | test_aoe.py::TestWriteDispatch::test_already_registered_is_success_without_writing | pass |
| S1.4 (boundary) | test_aoe.py::TestCommandDrift::test_drifted_row_is_renamed_before_the_add; test_aoe_real.py::test_repair_registers_the_correct_row_and_keeps_the_old_one | pass |
| S1.5 (negative) | ti::TestAoeRegister::test_s1_5_no_aoe_writes_nothing; ti::TestAoeRegister::test_s1_5_end_to_end_without_aoe | pass |
| S1.6 (boundary) | ti::TestAoeRegister::test_s1_6_group_title_and_worktree_reach_the_row; test_aoe.py::TestRegisterAoeOnly::test_flag_blocks_on_the_write | pass |
| S1.7 (negative) | ti::TestAoeScript::test_s1_7_an_acp_launcher_is_refused | pass |
| S1.8 (negative) | ti::TestAoeRegister::test_s1_8_create_aoe_only_is_an_unknown_option; test_aoe.py::TestRegisterAoeOnly::test_no_launch_verb_accepts_create_aoe_only | pass |
| S2.1 | ti::TestZed::test_s2_1_the_entry_runs_the_acp_launcher | pass |
| S2.2 (boundary) | ti::TestZed::test_s2_2_a_second_run_changes_no_byte | pass |
| S2.3 (boundary) | ti::TestZed::test_s2_3_only_the_entrys_lines_change; tj::test_the_edit_lands_and_every_comment_survives | pass |
| S2.4 (boundary) | ti::TestZed::test_s2_4_an_existing_entry_keeps_its_other_members | pass |
| S2.5 (boundary) | ti::TestZed::test_s2_5_a_missing_file_is_created; ti::TestZed::test_s2_5_a_file_with_no_agent_servers_gets_one | pass |
| S2.6 (negative) | ti::TestZed::test_s2_6_invalid_json_is_refused_and_left_as_it_was; tj::TestCli::test_a_file_that_is_not_utf8_is_refused_and_left_as_it_was | pass |
| S2.7 (negative) | ti::TestZed::test_s2_7_a_harness_with_no_acp_mode_is_refused | pass |
| S2.8 (boundary) | ti::TestZed::test_s2_8_the_container_entry_is_its_own | pass |
| S3.1 | ti::TestAtlas::test_s3_1_the_entry_runs_the_acp_launcher | pass |
| S3.2 (boundary) | ti::TestAtlas::test_s3_2_other_entries_keep_their_bytes | pass |
| S3.3 (boundary) | ti::TestAtlas::test_s3_3_the_directory_and_file_are_created | pass |
| S3.4 (negative) | ti::TestAtlas::test_s3_4_invalid_json_is_refused | pass |
| S3.5 (negative) | ti::TestAtlas::test_s3_5_a_harness_with_no_acp_mode_is_refused | pass |
| S4.1 | ti::TestVscode::test_s4_1_the_wrapper_is_the_claude_launcher; ti::TestVscode::test_s4_1_the_acp_launcher_still_registers_the_run_launcher | pass |
| S4.2 (boundary) | ti::TestVscode::test_s4_2_a_second_stack_replaces_the_value_on_its_line | pass |
| S4.3 (negative) | ti::TestVscode::test_s4_3_a_non_claude_harness_is_refused | pass |
| S4.4 | ti::TestVscodeWrapperArgv::test_s4_4_the_bundled_claude_is_dropped_and_the_rest_is_passthrough; ti::TestVscodeWrapperArgv::test_any_other_argv_is_left_as_it_is | pass |
| S4.5 (negative) | ti::TestVscode::test_s4_5_invalid_json_is_refused | pass |
| S4.6 (boundary) | ti::test_s4_6_the_wrapper_vscode_runs_starts_the_stacks_claude (the wrapper called as the extension calls it, fact 14; the panel UI itself is under the manual row) | pass |
| S4.7 (negative) | ti::TestVscode::test_s4_7_the_container_backend_is_refused | pass |
| S5.1 | ti::TestRunner::test_s5_1_the_contract_reaches_the_integration; ti::TestRunner::test_s5_1_the_container_backend_names_its_own_launchers | pass |
| S5.2 (boundary) | ti::TestRunner::test_s5_2_the_overlay_wins_over_the_repo_catalog | pass |
| S5.3 (negative) | ti::TestRunner::test_s5_3_an_unknown_name_lists_every_root_and_builds_nothing; ti::TestRunner::test_s5_3_no_build_runs_even_when_the_profile_is_missing | pass |
| S5.4 (negative) | ti::TestRunner::test_s5_4_a_register_file_that_is_not_executable_is_refused | pass |
| S5.5 (boundary) | ti::TestRunner::test_s5_5_the_launcher_exits_with_the_integrations_status; ti::TestRunner::test_s5_5_a_signal_death_is_128_plus_the_signal | pass |
| S5.6 (negative) | ti::TestRunner::test_s5_6_two_register_flags_are_refused; ti::test_two_flags_name_the_rule | pass |
| S5.7 (boundary) | ti::TestRunner::test_s5_7_a_flag_after_double_dash_is_passthrough | pass |
| S5.8 | ti::TestRunner::test_s5_8_the_environment_is_the_parents_plus_the_contract; ti::TestRunner::test_s5_8_a_stale_optional_name_in_the_parent_does_not_leak | pass |
| S6.1 | ti::TestNoAutomaticRegistration::test_s6_1_a_normal_launch_registers_nothing; test_adhoc_launch_is_not_persisted.py::TestHostRunLeavesNothingBehind::test_an_ordinary_stack_persists_nothing_either | pass |
| S6.2 (boundary) | test_aoe.py::TestForgetStack::test_removes_every_harness_of_the_named_stack | pass |
| S6.3 (negative) | ti::TestNoAutomaticRegistration::test_s6_3_no_aoe_integration_in_any_root_is_an_unknown_name | pass |
| S6.4 (boundary) | ti::TestNoAutomaticRegistration::test_s6_1_a_normal_launch_registers_nothing; test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s1_5_host_run_writes_them_before_the_harness_starts | pass |
| S7.1 | ti::TestBuildFirst::test_s7_1_the_build_runs_before_the_integration; ti::TestBuildFirst::test_s7_1_a_missing_profile_needs_a_build | pass |
| S7.2 (boundary) | ti::TestBuildFirst::test_s7_2_a_stale_stamp_needs_a_build; ti::TestBuildFirst::test_s7_3_the_real_stamp_check_reads_a_current_profile | pass |
| S7.3 (boundary) | ti::TestBuildFirst::test_s7_3_a_current_profile_needs_no_build; ti::TestRunner::test_s5_1_the_contract_reaches_the_integration | pass |
| S7.4 (negative) | ti::TestBuildFirst::test_s7_4_a_failed_build_runs_no_integration | pass |
| S7.5 | ti::test_s7_5_after_a_build_and_zed_the_acp_launcher_answers_initialize | pass |
| Must NOT: ACP stdout | ti::test_an_acp_register_run_writes_nothing_to_stdout | pass |
| Must NOT: no partial write | tj::TestCli::test_a_failed_rename_leaves_the_old_file; tj::TestCli::test_an_invalid_file_is_refused_and_left_as_it_was | pass |
| Must NOT: `harnessed build` runs no integration | ti::TestRunner::test_the_flag_is_read_only_on_a_global_verb | pass |
| Must NOT: launcher names (GH-565) | ti::TestRunner::test_s5_1_the_contract_reaches_the_integration (asserts `launchscript.global_name` paths); the existing launchscript suite, unchanged | pass |
| Must NOT: no credential value passed | ti::TestRunner::test_s5_8_the_environment_is_the_parents_plus_the_contract | pass |
| Must NOT: nothing host-local in `catalog/`, no new runtime dependency | `catalog/integrations/*/register` read in full: each uses only `HARNESSED_*`, `HOME` and `XDG_*` at run time; `pyproject.toml` unchanged in the diff | pass |
| Manual: the VS Code panel, the Zed panel and the Atlas list show and run the entry | manual: the user opens each app | unverified |

Story criteria, clause by clause:

| Clause | Test | Status |
|---|---|---|
| AC-1 condition: one row replays the launcher, exit 0, claude not started | S1.1 | pass |
| AC-1 boundary: second run leaves one row; a pre-change row is recognised and repaired | S1.2, S1.3, S1.4 | pass |
| AC-1 negative: no aoe, says so, non-zero, writes nothing | S1.5 | pass |
| AC-2 condition: the `agent_servers` entry with the ACP launcher | S2.1 | pass |
| AC-2 boundary: one entry after a second run; the rest of the file, comments included, unchanged | S2.2, S2.3 | pass |
| AC-2 negative: invalid JSON refused, file unchanged | S2.6 | pass |
| AC-3 condition: the Atlas entry with the same command | S3.1 | pass |
| AC-3 boundary: other entries stay; a missing file is created | S3.2, S3.3 | pass |
| AC-3 negative: invalid JSON refused, file unchanged | S3.4 | pass |
| AC-4 condition: the wrapper setting is the claude launcher | S4.1, S4.4 | pass |
| AC-4 condition: the Claude Code panel then runs claude through the stack | S4.6 | pass |
| AC-4 boundary: a second stack replaces the one value; the rest unchanged | S4.2 | pass |
| AC-4 negative: omp refused, non-zero, nothing written | S4.3 | pass |
| AC-5 condition: an overlay integration runs | S5.1 | pass |
| AC-5 boundary: the overlay copy wins over the repo copy | S5.2 | pass |
| AC-5 negative: an unknown name lists the available ones, non-zero | S5.3 | pass |
| AC-6 condition: a plain launch writes no aoe row and no editor entry | S6.1 | pass |
| AC-6 boundary: `harnessed rm` still removes aoe rows | S6.2 | pass |
| AC-6 negative: no aoe integration lists the available ones, non-zero | S6.3 | pass |
| AC-7 condition: a missing or stale profile is built before the integration | S7.1, S7.2 | pass |
| AC-7 condition: the ACP launcher then answers `initialize` with a result | S7.5 | pass |
| AC-7 boundary: a current profile is not rebuilt | S7.3 | pass |
| AC-7 negative: a failed build runs nothing, writes nothing, exits non-zero with the build's error | S7.4 | pass |

</details>

Break checks: every new test in `test_integrations.py` and `test_jsonc.py` was first seen failing, at collection, before its module existed. The four tests in commit 0d5622b were each seen failing against a mutant applied by hand. The S4.6 and S7.5 tests in 8687ad2 were each seen failing with their code path disabled (the wrapper argv rule; the build-first branch), and passing with it restored. S1.2 to S1.4 and S6.2 cite tests that predate this change and pass unchanged; this change does not touch `aoe.sync_session` or `aoe.forget_stack`.

### Gauntlet (final fresh run)
Every row PASSED.

<details>
<summary>6/6 layers PASSED</summary>

| Layer | Command | Status + result | Baseline | Selection | Log |
|---|---|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4765 passed, 79 skipped (baseline 4606 passed, 79 skipped) | reused | off | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 86.80% total (baseline 86.38%); integrations.py 100%, jsonc.py 99%; 4765 passed, 79 skipped | reused | off | work/coverage.log |
| types | pyright with the dev interpreter | PASSED — 0 errors, 0 warnings | reused | off | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — All checks passed | reused | off | work/lint.log |
| shellcheck | `shellcheck $(git ls-files "*.sh")` | PASSED — 0 findings | reused | off | work/shellcheck.log |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — no leaks found | reused | off | work/secrets.log |

</details>

Contract layers outside the manifest:

| Layer | Command | Status + result |
|---|---|---|
| property | Hypothesis tests in `tests/test_jsonc.py`, run inside the tests layer | PASSED — 5 properties, one at 300 examples |
| mutation | `mutmut run "harnessed.jsonc.*" "harnessed.integrations.*"` on a tree copy with `tests_dir` narrowed to the two new test files | integrations: 162 killed, 3 survived. jsonc: 521 killed, 46 survived, 4 timed out. Killed by hand against the final tests: 7 (integrations extract#23; jsonc container#24, _insert#49, _unit#15, and the 4 timeouts: skip#15, skip#17, skip#45, container#50). 45 left, all named below |
| shellcheck, by hand | `shellcheck -s sh catalog/integrations/*/register` | PASSED — exit 0, 0 findings |
| live | `live` and `live-docker` on the PR | not run here |
| manual | the VS Code panel, the Zed panel and the Atlas list | not run; the user's |

### Layers not run as specified
- N-A: none.
- UNAVAILABLE: live — runs on the PR, because `launcher.py` and `paths.py` are live triggers. It cannot run before a PR exists.
- UNAVAILABLE: manual — the VS Code, Zed and Atlas UIs need the apps and the user.
- SUBSTITUTED: real execution — `ti::test_an_acp_register_run_writes_nothing_to_stdout` runs a real child `python -m harnessed host-acp claude --stack hostmcp --register-zellij-only` against a real stamped profile. It cannot detect a defect in the build path (`_build_stack` was not run for real, because a build rewrites shared runtime state) or in an editor reading what was written.
- SUBSTITUTED: mutation scope — mutmut ran on a copy of the tree with `tests_dir` set to `tests/test_jsonc.py` and `tests/test_integrations.py`, so `pyproject.toml` stayed unchanged. It cannot show whether another test file kills a mutant. Its 4 timeouts were applied by hand and seen to fail.
- Named mutation exclusions (45), each equivalent or below what a test can observe:
  - `ensure_ascii=None` is falsy, the same as `False`: jsonc _dump#3, _dump#12, _insert#20, _insert#36, _insert#61, set_value#14.
  - A compact dump ignores `indent` and `unit`, and `multiline=None` is falsy: jsonc _insert#41, #42, #43, #48.
  - The interior of an empty object is whitespace or a comment of 4+ bytes, so a one-byte shorter slice or a wider strip set reaches the same branch: jsonc _insert#76, #78, #79, #80.
  - A `None` start equals 0, and a start of 1 differs only when byte 0 is the sole newline before `pos`, which no reachable member position has: jsonc _line_start#3, _line_start#10, __init__#4.
  - Strip sets that differ only in characters the parser rejects at that position: jsonc _starts_line#1, _starts_line#6, set_value#6.
  - A found newline or `*/` is at index 2 or later, so `< 0`, `<= 0` and `< 1` agree: jsonc skip#21, skip#22, skip#39, skip#40.
  - Locale-default encoding and `"UTF-8"` equal `"utf-8"` under a UTF-8 locale: jsonc read#2, read#5, read#8, write#25, write#29, write#34.
  - `newline=None` writes `\n` on POSIX: jsonc write#26, write#30.
  - The temporary file's name only: jsonc write#16, #17, #19, #20, #21, #22.
  - `unlink(missing_ok=...)` matters only when the temporary file is already gone: jsonc write#45, write#47.
  - Unreachable `AssertionError` text: jsonc set_value#94, #95, #96.
  - `check=None` or no `check` equals `check=False`: integrations run#5, run#9.

### Defect classes closed
- Generator: an exception `jsonc.read()` or `jsonc.set_value()` can raise that `jsonc.main` does not catch, so the user sees a traceback instead of the file and the reason.
- Enumerated by: reading `read`, `set_value` and `write` in `src/harnessed/jsonc.py` for every raise and every call that can raise.
- Sites: 4 — `JsoncError` (already caught); `OSError`, including `FileNotFoundError` and `IsADirectoryError` (already caught, `tj::TestCli::test_an_unreadable_file_exits_1`); `UnicodeDecodeError` (fixed in fc32ac1, `tj::TestCli::test_a_file_that_is_not_utf8_is_refused_and_left_as_it_was`); `ValueError` for no key (not applicable: `main` requires one key, `tj::TestCli::test_a_usage_error_exits_2`).

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 178506/2850 |
| spec-evidence-intent | 1 | claude-sonnet-5-5 | 71050/1205 |
| spec-evidence-intent | 2 | claude-sonnet-5-5 | 71185/1000 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 448585/6651 |
| spec-evidence-adversary | 2 | claude-sonnet-5-5 | 700208/11504 |

### Process notes
- RED for `jsonc.py`: the tests and the module were first drafted and run together outside the worktree, where they passed. In the worktree, the tests then ran first and failed at collection, before the module was added.
- Two of the new Zed tests failed on first run because of a test defect: they filtered lines by membership, and the new entry legitimately repeats lines like `"type": "custom",`. A difflib check that allows only one inserted block replaced it, which states S2.3 more strictly.
- The full suite found one ledger gap: `test_launch_parity.py` needed `_register_and_exit` in `CONTAINER_ONLY`, because `host_run` and `host_acp` call it themselves (12996cb).
- mutmut's clean run failed `HealthCheck.differing_executors` on Hypothesis tests written as methods. They became module functions with their assertions unchanged (12996cb).
- The first mutation run left 137 mutants not killed. Tests in 4813ce3 and 0d5622b killed all but the 45 named above. The test helper `run()` had read `SystemExit(None)` as 1, which let a `None` exit code pass; it now reads it as 0.
- A gauntlet run at 4813ce3 was discarded, because tests were edited during it. A later run was stopped so the evidence inputs could be committed and the stamp would read a clean tree.
- The first final gauntlet went red on `tests/test_host_acp.py::TestAdversaryRound3::test_a_setup_child_that_ignores_term_is_still_stopped` with `ProcessLookupError`, under the coverage layer only. The test's `_gone` helper reads `/proc/<pid>/stat` while the process exits. It passed 6 of 6 repeats under coverage, and this change does not touch that file or the relay. The rerun was green and is the run cited.
- Evidence gates, pass 1: Gate 2 not-ready (AC-4, AC-7) and Gate 2a not-ready (S4.6, S7.5), both for the clauses then mapped as manual. Pass 2 adds the two tests in 8687ad2, reruns the gauntlet, and rewrites this report.
- Mutation testing ran under a copy of the tree; mise printed "not trusted" warnings for that copy's `mise.toml`, which do not affect the Python run.
