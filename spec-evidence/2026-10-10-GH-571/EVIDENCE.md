## Evidence Report — host-acp: run a stack as an ACP agent on the host (Tier 3)

## Summary
**Delivered.** `harnessed host-acp <omp|claude> --stack <name>` runs a stack as an ACP agent on the host, for an editor that reuses one agent process across projects. It does the per-stack half of `host-run` once, starts `omp acp` or `claude-agent-acp`, and relays JSON-RPC. The first `session/new` for a folder runs the new `project-setup` verb there first. `build` and `install` write the host ACP launcher, `build <stack> claude` offers to install the pinned adapter, and `tools/acp-smoke.py` drives `host-acp`. Why: Atlas reuses one process per entry, and `container-acp` cannot follow each session's folder.

**Each criterion and its proof.**
- AC-1: stdout carries only JSON-RPC for omp and claude, launch and init output go to stderr, and `opencode` exits 2 before any work. Proven by real-process tests (S1.1 to S1.5) and by both smoke runs.
- AC-2: `initialize` answers within 60 s, and an unbuilt stack is refused with the build command named. Proven by S2.2 and by both smoke runs with `--launch-timeout 60`. The smoke runs used the `hostspike` stack, not `gortex-ghissues` (see Not proven).
- AC-3: one process serves two folders, and a missing folder is a JSON-RPC error. Proven by relay tests (S3.1 to S3.3, S3.5, S3.6) and, for the real agents, by the `--check-cwd` smoke runs: omp and claude each reported folder A, then folder B.
- AC-4: the first session in a folder runs `project-setup` once, a failure is a JSON-RPC error, and `host-run` runs the same steps in the same order with its existing tests unchanged. Proven by S4.1 to S4.6 and the full suite.
- AC-5: claude gets the stack's MCP file and strict by default, and `--no-strict-mcp-config` drops strict. Proven by S5.1 to S5.4 and the existing wrapper tests.
- AC-6: `build <stack> claude` asks the exact question and honours y, n and c; `host-acp claude` without the adapter refuses on stderr. Proven by S6.1 to S6.10.
- AC-7: `build` writes `harnessed-acp-<harness>-<stack>-host` for omp and claude, and `uninstall` removes it. Proven by S7.1 to S7.4.
- AC-8: `tools/acp-smoke.py` passes for omp and claude against `host-acp`, from a new empty folder. Proven by S8.1 to S8.3.

**Not proven.** Mutation testing did not run: the engineer stopped it before it scored any mutant. The `live.yml` layer has not run yet; it runs on the pull request. S2.1 ran on `hostspike`, not `gortex-ghissues`. A fresh wheel install of the claude wrapper path was not exercised.

**Judgment calls.** Existing tests were kept unchanged wherever they pinned `host-run`'s call sites and order (engineer's ruling), so `host-run` and `project-setup` run the same four steps rather than share one function (Revisions 3 and 4). The adapter version is asked with `--version`, because pnpm and mise layouts defeat a `package.json` lookup (Revision 5). Tests that pinned "no host ACP launcher" changed by design for AC-7.

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: `host-acp` and `project-setup` verbs, the host ACP launcher, the build-time adapter offer, and a smoke script that drives `host-acp`.
- Proven: 48/48 scenarios mapped and passing (S2.1 on a substituted stack).
- Not proven: mutation layer (not run, stopped by the engineer); live layer (`live.yml`, runs on the PR, not yet run); S2.1 stack substituted (`hostspike` for `gortex-ghissues`); fresh-wheel install of the claude wrapper path (unverified).

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-10-GH-571/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit 9dbf591, "GH-571: spec approved")
- Intent review: round 1 changed the SPEC (S3 states that S3.4 is the required proof for real agents; S6 counts another installed version as not installed; S7.5 cut; S5.4 added once Decide 2 was ruled); round 2 changed nothing
- Source state: commit 087249aaa8b174dd71b62be2fa5d708ccbc83543 — the commit the final run and adversary round 2 read
- Stamp:

```json
{
  "result": "green",
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
    "tests": 372.226,
    "coverage": 408.103,
    "types": 56.327,
    "lint": 0.458,
    "shellcheck": 5.53,
    "secrets": 9.507
  },
  "failed": null,
  "exit_code": 0,
  "commit": "087249aaa8b174dd71b62be2fa5d708ccbc83543",
  "dirty": false,
  "written": "2026-10-10T19:44:24.443Z"
}
```

- Baseline: spec-evidence/2026-10-10-GH-571/baseline-stamp.json at commit 9dbf591ece158dc9d481791315a1f2f0802a811f, green

### Spec → Test mapping
Test ids are relative to the repository root. `HA` is `tests/test_host_acp.py`, `BA` is `tests/test_launcher_build_adapter.py`. The smoke logs are the final runs on commit 087249a.

| Scenario | Test | Status |
|---|---|---|
| S1.1 | `HA::TestStdoutIsJsonRpcOnly::test_s1_1_and_s1_3_initialize_and_session_new_answer_on_a_clean_stdout[omp]` | pass |
| S1.2 | `HA::TestStdoutIsJsonRpcOnly::test_s1_2_launch_and_init_output_go_to_stderr` | pass |
| S1.3 | `HA::TestStdoutIsJsonRpcOnly::test_s1_1_and_s1_3_initialize_and_session_new_answer_on_a_clean_stdout[claude]` | pass |
| S1.4 | `HA::TestStdoutIsJsonRpcOnly::test_s1_4_the_launch_folder_gets_no_per_project_setup` | pass |
| S1.5 | `HA::TestStdoutIsJsonRpcOnly::test_s1_5_a_harness_without_acp_is_refused_before_any_work` | pass |
| S2.1 | `tools/acp-smoke.py --verb host-acp --launch-timeout 60`, logs `spec-evidence/2026-10-10-GH-571/smoke-host-acp-omp.log:24` and `spec-evidence/2026-10-10-GH-571/smoke-host-acp-claude.log:38` (stack `hostspike`, substituted for `gortex-ghissues`) | pass |
| S2.2 | `HA::TestUnbuiltStack::test_s2_2_an_unbuilt_stack_names_the_build_command` | pass |
| S3.1 | `HA::TestOneProcessManyProjects::test_s3_1_each_session_reports_its_own_folder` | pass |
| S3.2 | `HA::TestOneProcessManyProjects::test_s3_2_the_agent_gets_each_cwd_unchanged` | pass |
| S3.3 | `HA::TestOneProcessManyProjects::test_s3_3_a_missing_cwd_is_an_error_and_never_reaches_the_agent` | pass |
| S3.4 | `tools/acp-smoke.py --check-cwd`, logs `spec-evidence/2026-10-10-GH-571/smoke-host-acp-omp.log:21,23` and `spec-evidence/2026-10-10-GH-571/smoke-host-acp-claude.log:35,37` | pass |
| S3.5 | `HA::test_s3_5_concurrent_writers_never_interleave_a_line` (hypothesis, 200 examples) | pass |
| S3.6 | `HA::test_s3_6_every_other_line_is_forwarded_byte_for_byte` (hypothesis, 200 examples) | pass |
| S4.1 | `HA::TestPerProjectSetup::test_s4_1_the_first_session_runs_setup_before_the_agent_sees_it` | pass |
| S4.2 | `HA::TestPerProjectSetup::test_s4_2_a_second_session_in_the_same_project_does_not_rerun_it` | pass |
| S4.3 | `HA::TestFailedSetup::test_s4_3_a_failed_setup_is_an_error_naming_the_project` | pass |
| S4.4 | `HA::TestFailedSetup::test_s4_4_a_failed_project_is_set_up_again_next_time` | pass |
| S4.5 | `HA::TestHostRunSharesTheSetup::test_s4_5_host_run_and_project_setup_run_the_same_steps_in_the_same_order`, plus every test in the six named files unchanged (gauntlet tests layer) | pass |
| S4.6 | `HA::TestHostRunSharesTheSetup::test_s4_6_project_setup_alone_sets_up_one_project` | pass |
| S5.1 | `HA::TestClaudeMcpAndEnv::test_s5_1_the_adapter_gets_the_stack_mcp_file_and_strict` | pass |
| S5.2 | `HA::TestClaudeMcpAndEnv::test_s5_2_no_strict_keeps_the_file_and_drops_strict` | pass |
| S5.3 | `tests/test_acp_verb.py::TestTheClaudeWrapper::test_strict_adds_the_hub_and_strict_before_the_sdk_args` (existing) | pass |
| S5.4 | `HA::TestClaudeMcpAndEnv::test_s5_4_the_agent_gets_per_stack_env_only[omp]` and `[claude]` | pass |
| S6.1 | `BA::TestTheOffer::test_s6_1_a_missing_or_other_version_asks_exactly[None]` and `[0.84.0]` | pass |
| S6.2 | `BA::TestTheOffer::test_s6_2_yes_runs_the_npm_install` | pass |
| S6.3 | `BA::TestTheOffer::test_s6_3_c_runs_the_typed_command_through_bash` | pass |
| S6.4 | `BA::TestTheOffer::test_s6_4_no_runs_nothing_and_builds_on` | pass |
| S6.5 | `BA::TestTheOffer::test_s6_5_the_pinned_version_asks_nothing` | pass |
| S6.6 | `BA::TestTheOffer::test_s6_6_a_failed_install_warns_and_builds_on` | pass |
| S6.7 | `BA::TestTheOffer::test_s6_7_no_terminal_asks_nothing_and_names_the_command` | pass |
| S6.8 | `HA::TestTheAdapterAtLaunch::test_s6_8_a_missing_adapter_refuses_on_stderr` | pass |
| S6.9 | `BA::TestTheOffer::test_s6_9_omp_never_checks_the_adapter` | pass |
| S6.10 | `HA::TestTheAdapterAtLaunch::test_s6_10_another_version_runs_with_a_warning` | pass |
| S7.1 | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_1_build_writes_the_host_acp_launcher[omp]` and `[claude]`; `tests/test_launchscript.py::TestWriteGlobals::test_gh571_s7_1_a_host_acp_launcher_is_written[omp]` and `[claude]` | pass |
| S7.2 | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_2_a_second_build_leaves_one_identical_launcher` | pass |
| S7.3 | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_3_uninstall_removes_what_build_wrote` | pass |
| S7.4 | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_4_no_host_acp_launcher_without_acp[opencode]`, `[antigravity]`, `[codex]` | pass |
| S8.1 | `tools/acp-smoke.py ... --harness omp --verb host-acp`, log `spec-evidence/2026-10-10-GH-571/smoke-host-acp-omp.log:24` | pass |
| S8.2 | `tools/acp-smoke.py ... --harness claude --verb host-acp`, log `spec-evidence/2026-10-10-GH-571/smoke-host-acp-claude.log:38` | pass |
| S8.3 | `tests/test_acp_smoke.py::test_s8_3_container_acp_argv_is_unchanged`; also `test_s8_host_acp_argv_names_no_project`, `test_s8_the_default_verb_is_container_acp` | pass |
| AC-1 condition | S1.1, S1.3 tests above | pass |
| AC-1 boundary | `HA::TestStdoutIsJsonRpcOnly::test_s1_2_launch_and_init_output_go_to_stderr` | pass |
| AC-1 negative | `HA::TestStdoutIsJsonRpcOnly::test_s1_5_a_harness_without_acp_is_refused_before_any_work` | pass |
| AC-2 condition | S2.1 smoke runs with `--launch-timeout 60` | pass |
| AC-2 boundary | the 60 s limit is `--launch-timeout 60` in both smoke runs | pass |
| AC-2 negative | `HA::TestUnbuiltStack::test_s2_2_an_unbuilt_stack_names_the_build_command` | pass |
| AC-3 condition | `HA::TestOneProcessManyProjects::test_s3_1_each_session_reports_its_own_folder`; S3.4 smoke runs | pass |
| AC-3 boundary | one process, two folders: S3.4 smoke runs (`--check-cwd`) | pass |
| AC-3 negative | `HA::TestOneProcessManyProjects::test_s3_3_a_missing_cwd_is_an_error_and_never_reaches_the_agent` | pass |
| AC-4 condition | `HA::TestPerProjectSetup::test_s4_1_the_first_session_runs_setup_before_the_agent_sees_it` | pass |
| AC-4 boundary | `HA::TestPerProjectSetup::test_s4_2_a_second_session_in_the_same_project_does_not_rerun_it`; `HA::TestHostRunSharesTheSetup::test_s4_5_host_run_and_project_setup_run_the_same_steps_in_the_same_order` | pass |
| AC-4 negative | `HA::TestFailedSetup::test_s4_3_a_failed_setup_is_an_error_naming_the_project` | pass |
| AC-5 condition | `HA::TestClaudeMcpAndEnv::test_s5_1_the_adapter_gets_the_stack_mcp_file_and_strict` | pass |
| AC-5 boundary | `HA::TestClaudeMcpAndEnv::test_s5_2_no_strict_keeps_the_file_and_drops_strict` | pass |
| AC-5 negative | `tests/test_acp_verb.py::TestTheClaudeWrapper::test_strict_adds_the_hub_and_strict_before_the_sdk_args` | pass |
| AC-6 condition | `BA::TestTheOffer::test_s6_1_a_missing_or_other_version_asks_exactly[None]`, `test_s6_2_yes_runs_the_npm_install`, `test_s6_3_c_runs_the_typed_command_through_bash`, `test_s6_4_no_runs_nothing_and_builds_on` | pass |
| AC-6 boundary | `BA::TestTheOffer::test_s6_5_the_pinned_version_asks_nothing` | pass |
| AC-6 negative | `HA::TestTheAdapterAtLaunch::test_s6_8_a_missing_adapter_refuses_on_stderr` | pass |
| AC-7 condition | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_1_build_writes_the_host_acp_launcher[omp]` and `[claude]`; `test_gh571_s7_3_uninstall_removes_what_build_wrote` | pass |
| AC-7 boundary | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_2_a_second_build_leaves_one_identical_launcher` | pass |
| AC-7 negative | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_4_no_host_acp_launcher_without_acp[opencode]`, `[antigravity]`, `[codex]` | pass |
| AC-8 condition | S8.1 and S8.2 smoke runs, started in a new empty folder with no project path in the args (log line 1 of each) | pass |

Tests changed by design for AC-7 (each listed with its old and new assertion):
- `tests/test_launchscript.py::TestWriteGlobals::test_s1_12_no_host_acp_launcher_is_written`: asserted the host ACP launcher is absent; replaced by `test_gh571_s7_1_a_host_acp_launcher_is_written`, which asserts it is written with `exec harnessed host-acp <harness> --stack default "$@"`.
- `tests/test_launchscript.py::TestWriteGlobals::test_s1_1_three_launchers_for_claude`, renamed `test_s1_1_four_launchers_for_claude`: expected set gains `harnessed-acp-claude-default-host`.
- `tests/test_launchscript.py::TestWriteGlobals::test_s1_5_no_global_launcher_names_a_path`: allowed verbs gain `host-acp`.
- `tests/test_launchscript.py::TestWriteGlobals::test_s1_11_an_unwritable_dir_never_raises`: `len(refused) == 3` becomes `4`.
- `tests/test_launchscript.py::TestRemoveGlobals::test_s5_1_only_the_named_pair_goes`: removed and remaining sets gain the host ACP launchers.
- `tests/test_launchscript.py::TestGlobalWriterMutationGaps::test_a_missing_launcher_does_not_stop_removal_of_the_rest` and `test_a_foreign_file_does_not_stop_removal_of_the_rest`: removed set gains `harnessed-acp-claude-default-host`.
- `tests/test_launcher_install.py::TestInstallWritesGlobalLaunchers::test_s1_1_install_writes_three_launchers`, renamed `test_s1_1_install_writes_four_launchers`: expected set gains `harnessed-acp-claude-claude_time-host`.
- `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s5_1_only_the_named_pair_is_removed`, `test_s5_2_referencing_rows_are_named`, `test_only_removed_launchers_are_looked_up`: sets gain the host ACP launcher.
- `tests/test_adhoc_launch_is_not_persisted.py`: `_HOSTSPIKE_LAUNCHERS` and `test_s1_6_container_run_writes_them_without_a_build` gain the host ACP launcher.
- `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_s1_4_build_writes_them`: expected set gains `harnessed-acp-claude-default-host`.

### Gauntlet (final fresh run)
| Layer | Command | Status + result | Log |
|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4202 passed, 80 skipped, 0 failed | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 85.62% total (80% required); `acprelay.py` 93%, `launchscript.py` 99% | work/coverage.log |
| types | pyright, as `tools/gauntlet-layers.json` declares | PASSED — 0 errors, 0 warnings | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — 0 findings | work/lint.log |
| shellcheck | `mise exec -- sh -c 'shellcheck $(git ls-files "*.sh")'` | PASSED — 0 findings | work/shellcheck.log |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — no leaks | work/secrets.log |
| property | hypothesis inside the tests layer: S3.5 and S3.6, 200 examples each | PASSED | work/tests.log |
| adversarial review | `spec-evidence-adversary`, 2 rounds | PASSED — round 1: 0 findings, 4 hunches, all fixed in 087249a with tests seen failing; round 2 (on 087249a): 0 findings, 2 hunches declined with evidence | findings-code-round1.md, findings-code.md |
| real execution | `tools/acp-smoke.py --verb host-acp` for omp and claude, on 087249a | PASSED — 9 `ok` lines and `PASS` each | smoke-host-acp-omp.log, smoke-host-acp-claude.log |

### Layers not run as specified
- N-A: none.
- UNAVAILABLE: none.
- SUBSTITUTED: S2.1 real-agent timing ran on the `hostspike` stack in an isolated `XDG_DATA_HOME`, not on `gortex-ghissues`. That stack is built only for claude on this machine, and building it for omp would rewrite runtime state that live sessions share. It cannot detect a slow per-stack setup specific to `gortex-ghissues`, such as long tool installs.
- NOT RUN: mutation (`mutmut run "harnessed.acprelay.x_*" "harnessed.launchscript.x_global_verbs*"`). Started, then stopped by the engineer during mutant generation, before any mutant was scored. It would catch assertions too weak to kill a changed relay branch.
- NOT RUN YET: live (`live.yml`, both jobs). It triggers on `src/harnessed/launcher.py` and runs on the pull request.

### Defect classes closed
- Generator: a daemon thread blocked on a buffered read at interpreter shutdown.
- Enumerated by: `rg -n 'daemon=True' src tools`
- Sites: 4 — `src/harnessed/acprelay.py:129` `from_editor`: fixed (host-acp ends with `os._exit`; test `HA::TestTheAgentExitsFirst`); `src/harnessed/acprelay.py:127` `from_agent`: not applicable (it reads the agent's stdout to EOF, and `run` joins it); `tools/acp-smoke.py:141` `_reader`: not applicable (it reads to EOF, and the script waits for EOF before exit); `src/harnessed/proc.py:154` `_pump` (pre-existing): not applicable (it reads a child's stdout to EOF and is joined after the child exits).

- Generator: a source-text test pins a call site or an order in `_launch_host`, so moving a call out of `_launch_host` breaks it even when the behavior holds.
- Enumerated by: the full tests layer, which failed `test_lock_spans_the_installs_not_just_the_rebuild`, `test_the_host_sequencer_really_prints_the_gap` and `test_no_unexplained_container_only_capability` when the calls moved.
- Sites: 3 — all already correct once `host-run` kept every per-project call at its original site (Revisions 3 and 4); none of these tests changed.

### Not reached by review
- Round 1: calls 3/10; hunts not reached: 1 (merge-gate argument comparison: I did not open the workflows or tools/gauntlet-layers.json), 2 (call sites of changed functions beyond _launch_host and provision_tools), 4 (property-test and parser inputs in the second half of tests/test_host_acp.py), 8 (EVIDENCE report orientation against its tables), 10 (docs: README documents host-acp, so I expect no finding); sites not opened: /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/spec-evidence/2026-10-10-GH-571/work/diff.txt lines 938-1901 (rest of tests/test_host_acp.py, tools/acp-smoke.py, remaining test and catalog diffs), /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/.github/workflows/lint.yml, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/tools/gauntlet-layers.json, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/src/harnessed/launcher.py:3002 wire_services body, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/src/harnessed/launcher.py:4825-4930 uninstall path for the new host-acp launcher
- Round 2: calls 3/10; hunts not reached: 1 (workflows test.yml, lint.yml and live.yml not opened, so I did not compare their argument lists with the layer commands), 2 (call sites of project_setup, _launch_host's other callers, and the uninstall path), 4 (property tests and parser inputs in tests/test_host_acp.py past line 915), 8 (no EVIDENCE report in the diff head I read), 10 (README documents host-acp, so I expect no finding); sites not opened: /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/spec-evidence/2026-10-10-GH-571/work/diff.txt lines 916-1980, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/.github/workflows/lint.yml, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/.github/workflows/live.yml, /home/mcrowe/Programming/Personal/harnessed/3-3-gh-571-host-acp/tools/acp-smoke.py

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 125472/1283 |
| spec-evidence-intent | 1 | claude-sonnet-5-5 | 63539/238 |
| spec-evidence-intent | 2 | claude-sonnet-5-5 | 64561/238 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 237603/1439 |
| spec-evidence-adversary | 2 | claude-sonnet-5-5 | 148960/990 |

### Honest notes
- A pre-build spike (`omp acp` driven directly, two sessions) confirmed that omp honours the `session/new` cwd before any code was written.
- Gauntlet run 1 (on 2ad839f) failed two existing source-text tests. Gauntlet run 2 (on 53686a6) failed six tests, because I edited `launcher.py` while it ran and `inspect.getsource` read line numbers that no longer matched; all six passed on the unchanged tree. The final run (on 087249a) was started with a clean tree, and nothing was edited while it ran.
- The claude smoke run found two defects that the unit tests had not: adapter detection failed on the pnpm and mise layouts (Revision 5), and `host-acp` aborted at shutdown when the agent exited first. Both were fixed with tests seen failing first.
- The first claude smoke run also failed because the test command set `XDG_DATA_HOME` to a scratch folder, which hid mise's own installs. The final runs set `MISE_DATA_DIR` to the real mise data folder. That was a fault of the test command, not of the product.
- The claude adapter was installed by the engineer's instruction with `mise use -g npm:@agentclientprotocol/claude-agent-acp@0.85.1`, which wrote the user's global mise config.
- `src/harnessed/__main__.py` shows 0% coverage: only the `python -m harnessed` subprocess in S4.6 runs it, and coverage does not follow subprocesses. S4.6 passing is its proof.
- AC-4 says `host-run` "runs the same verb". `host-run` runs the same four steps, in the same order, at its own call sites, not by calling `project-setup` (Revision 4, by the engineer's ruling to keep existing tests unchanged).
