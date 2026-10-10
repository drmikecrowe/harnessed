## Evidence Report — Global launchers, local launcher only for aoe (Tier 3)

## Summary

**What was delivered, and why.** Every stack you install, build or launch now gets one command per backend in `~/.local/bin`, such as `harnessed-claude-default-container`. Run it from any folder and it launches that stack there. A launch writes a launcher into your project only when aoe is usable, and that launcher calls the global one. `install` and `uninstall` now take `<stack> <harness>`. The old `~/.local/bin/<stack>` shim is no longer written, and `uninstall` removes one only when its exec line is exactly the old shim's. This gives editors and aoe one stable command per stack, and a launch outside aoe leaves nothing in the repo.

**Each criterion and how it was proven.**
- AC-1, launchers are written: S1.1 to S1.11, tested against the writer, `install`, `build`, `host-run` and `container-run` (13 tests).
- AC-2, a launcher launches where it runs and passes arguments through; no aoe means no project file: S2.1 to S2.3, by executing the real launcher against a stub `harnessed`.
- AC-3, the local launcher exists only for aoe and calls the global one: S3.1 to S3.5, including running local launcher, then global launcher, then `harnessed` end to end from another folder.
- AC-4, `harnessed rm` attribution: S4.1 to S4.4, including the real `rm` command against recorded aoe rows.
- AC-5, `uninstall` removes exactly one pair and names the rows it strands: S5.1 to S5.4.
- AC-6, the old shim: S6.1 to S6.4.

All 31 scenarios pass in the final run: 4141 tests passed and 80 skipped, against a baseline of 4056 passed. Coverage is 85.95% (threshold 80%), and pyright, ruff, shellcheck and gitleaks report zero findings.

**What is not proven.**
- `live.yml` (the container layer) runs only on the pull request, so it has not run yet.
- Changed-line coverage was substituted by whole-project coverage.
- Mutation testing ran on the changed functions, not whole changed files.
- The adversarial review is bound to `5149831`. Two later commits came after it: a test-only commit and a config-only commit.
- The final stamp says `dirty: true`. The cause is three untracked evidence files under `spec-evidence/`, not source.

**Judgment calls made during the build.**
- `--create-aoe-only` bypasses the aoe check, so a missing aoe is still reported as an error.
- `install` exits 1 when a launcher cannot be written; launches only warn.
- `build --root` writes no global launchers.
- A symlink at a launcher's name is never written through or removed.
- `uninstall` reports rows only for launchers it actually removed. This fix came from adversary round 1.
- Existing tests changed: `TestInstallShim` was replaced, and two tests from the SPEC's rewrite list changed, `test_an_ordinary_stack_still_persists` and `TestParityWithCommandFor`. Revision 4 adds five more. Each keeps the decision it encodes.

## Orientation

- Verdict: ready for review. Every scenario passes, and the gauntlet is green.
- Delivered: global launchers in `~/.local/bin`, written by `install`, `build`, `host-run` and `container-run`, and removed by `uninstall`. The local launcher is written only for aoe and execs the global launcher. `rm` attributes rows by the exec'd global name.
- Proven: S1.1 to S6.4 (31 scenarios), the full suite, coverage, types, lint, shellcheck, secrets, a property round trip, real execution, and two adversary rounds.
- Not proven: `live.yml` (UNAVAILABLE until the PR), changed-line coverage (SUBSTITUTED), mutation over whole changed files (SUBSTITUTED), and adversarial review of `2acfc39` and `4eb4543` (not run; test-only and config-only).
- Stamp: `gauntlet-stamp.json`, result green, commit `2acfc39c7c6d48df9510a6952333a45de3cc00ca`, `dirty: true`. The only uncommitted files at the run's start were `baseline-stamp.json`, `findings-code.md` and `findings-code-round1.md` in this story directory, and no source.
- Process: spec-evidence 0.0.1
- Intent review: round 1 added S3.4 and reworded S1.5, and its one other point was declined (S3.2 tests a Story rule). Round 2 named the per-launch flags in S3.1 and added S3.5 and S5.4.

### Spec → Test mapping

| Scenario | Test | Status |
|---|---|---|
| S1.1 | `tests/test_launcher_install.py::TestInstallWritesGlobalLaunchers::test_s1_1_install_writes_three_launchers`, `tests/test_launchscript.py::TestWriteGlobals::test_s1_1_three_launchers_for_claude` | pass |
| S1.2 | `tests/test_launcher_install.py::TestInstallWritesGlobalLaunchers::test_s1_2_codex_gets_no_acp_launcher`, `tests/test_launchscript.py::TestWriteGlobals::test_s1_2_no_acp_launcher_for_codex` | pass |
| S1.3 | `tests/test_launchscript.py::TestWriteGlobals::test_s1_3_dotted_stack` (the writer `install` calls), `tests/test_launchscript.py::test_global_name_round_trips` | pass |
| S1.4 | `tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_s1_4_build_writes_them` | pass |
| S1.5 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s1_5_host_run_writes_them_before_the_harness_starts`, `tests/test_launchscript.py::TestWriteGlobals::test_s1_5_no_global_launcher_names_a_path` | pass |
| S1.6 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s1_6_container_run_writes_them_without_a_build` | pass |
| S1.7 | `tests/test_launchscript.py::TestWriteGlobals::test_s1_7_identical_launcher_is_not_rewritten` | pass |
| S1.8 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s1_8_a_foreign_launcher_is_kept_and_named`, `tests/test_launchscript.py::TestWriteGlobals::test_s1_8_a_foreign_file_is_left_alone` | pass |
| S1.9 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s1_9_an_adhoc_stack_gets_none` | pass |
| S1.10 | `tests/test_launcher_install.py::TestInstallWritesGlobalLaunchers::test_s1_10_unknown_stack_exits_nonzero_and_writes_nothing` | pass |
| S1.11 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s1_11_an_unwritable_bin_dir_warns_and_launches`, `tests/test_launchscript.py::TestWriteGlobals::test_s1_11_an_unwritable_dir_never_raises` | pass |
| S2.1 | `tests/test_launchscript.py::TestRunningAGlobalLauncher::test_s2_1_cwd_is_the_project` | pass |
| S2.2 | `tests/test_launchscript.py::TestRunningAGlobalLauncher::test_s2_2_separator_and_agent_flags_pass_through` | pass |
| S2.3 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s2_3_no_usable_aoe_leaves_nothing_in_the_project`, `tests/test_adhoc_launch_is_not_persisted.py::TestThePersistGate::test_s2_3_without_a_usable_aoe_nothing_persists` | pass |
| S3.1 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s3_1_the_local_launcher_execs_the_global_one`, `tests/test_launchscript.py::TestTheLocalLauncherExecsTheGlobalOne::test_s3_1_body` | pass |
| S3.2 | `tests/test_launchscript.py::TestTheLocalLauncherExecsTheGlobalOne::test_s3_2_aoe_flags_stay_local` | pass |
| S3.3 | `tests/test_adhoc_launch_is_not_persisted.py::TestGlobalLaunchersAtLaunch::test_s3_3_container_acp_writes_no_local_launcher` | pass |
| S3.4 | `tests/test_launchscript.py::TestTheLocalLauncherExecsTheGlobalOne::test_s3_4_the_project_is_the_launchers_folder` | pass |
| S3.5 | `tests/test_aoe.py::TestGlobalLauncherRows::test_s3_5_the_row_shape_is_still_ours` | pass |
| S4.1 | `tests/test_aoe.py::TestGlobalLauncherRows::test_s4_1_a_new_format_row_is_removed_by_rm` | pass |
| S4.2 | `tests/test_aoe.py::TestGlobalLauncherRows::test_s4_2_an_old_stack_flag_row_is_still_removed` | pass |
| S4.3 | `tests/test_aoe.py::TestGlobalLauncherRows::test_s4_3_a_dotted_neighbour_stays` | pass |
| S4.4 | `tests/test_aoe.py::TestRmLeavesGlobalLaunchersAlone::test_s4_4_rm_changes_no_global_launcher` | pass |
| S5.1 | `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s5_1_only_the_named_pair_is_removed`, `tests/test_launchscript.py::TestRemoveGlobals::test_s5_1_only_the_named_pair_goes` | pass |
| S5.2 | `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s5_2_referencing_rows_are_named`, `tests/test_aoe.py::TestRowsReferencing::test_s5_2_a_referencing_row_is_named` | pass |
| S5.3 | `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s5_3_a_foreign_launcher_is_named_and_kept`, `tests/test_launchscript.py::TestRemoveGlobals::test_s5_3_a_foreign_file_is_not_removed` | pass |
| S5.4 | `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s5_4_no_rows_prints_no_row_path`, `tests/test_aoe.py::TestRowsReferencing::test_s5_4_no_referencing_row_is_an_empty_list` | pass |
| S6.1 | `tests/test_launcher_install.py::TestInstallWritesGlobalLaunchers::test_s6_1_install_writes_no_old_shim` | pass |
| S6.2 | `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s6_2_the_old_shim_is_removed` | pass |
| S6.3 | `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s6_3_a_second_uninstall_finds_no_shim` | pass |
| S6.4 | `tests/test_launcher_install.py::TestUninstallRemovesGlobalLaunchers::test_s6_4_a_file_that_is_not_the_old_shim_is_kept` | pass |

Must NOT mapping:

| Must NOT | Proof |
|---|---|
| Legacy names and `--stack` exec lines stay attributable | S4.2; the existing legacy-name tests in `tests/test_aoe.py::TestForgetStackReadsTheLauncherScript` pass unchanged |
| `acp` never a backend in a local name | `tests/test_launchscript.py::TestGlobalNames::test_acp_is_a_backend_only_in_a_global_name` |
| Never overwrite or delete a `~/.local/bin` file without the sentinel | S1.8, S5.3, S6.4, `test_the_sentinel_must_be_on_line_one_or_two`, `test_a_symlink_is_never_written_through_or_removed` |
| A launcher write failure never ends a launch | S1.8, S1.11 |
| No second quoting | `tests/test_launchscript.py::TestParityWithCommandFor`, `TestHostileInput` (executed scripts) |
| `--stack` before `"$@"` in a global launcher | `tests/test_launcher_install.py::TestInstallWritesGlobalLaunchers::test_stack_flag_precedes_user_args_so_passthrough_survives`, S2.2 |
| `host-run` / `container-run` / `container-acp` arguments unchanged | no signature changed in the diff; the full suite passes |
| `rm` touches no host row and no `~/.local/bin` file | S4.4; the existing `test_a_host_script_is_left_alone_by_the_container_verb` passes |
| Test count not below baseline, except the named rewrites | baseline 4056 passed, final 4141 passed; every rewrite is named in the SPEC's Must NOT line and in `decisions.md` revision 4 |

### Gauntlet (final fresh run)

Run with `node <scripts>/gauntlet.mjs` at commit `2acfc39`, stamp written 2026-10-10T11:25:26Z.

| Layer | Command | Result | Status |
|---|---|---|---|
| Merge gate parity | `test.yml` pytest; `lint.yml` ruff `src tests tools`, pyright, shellcheck | each mapped to the layer below with the gate's arguments | PASSED |
| Full test suite | `mise exec -- tools/run-tests.sh` | 4141 passed, 80 skipped, 0 failed, randomized order (baseline 4056 passed) | PASSED |
| Coverage | `pytest -q --cov=src --cov-branch --cov-fail-under=80` | 85.95% (`launchscript.py` 99%, `paths.py` 99%, `aoe.py` 94%, `launcher.py` 70%) | PASSED |
| Static types | pyright as `lint.yml` runs it | 0 errors | PASSED |
| Lint | `ruff check src tests tools` | 0 findings | PASSED |
| Shellcheck | `shellcheck $(git ls-files "*.sh")` | 0 findings | PASSED |
| Secrets | `gitleaks detect --no-banner` | 0 unignored findings | PASSED |
| Changed-line coverage | whole-project coverage above | not run as diff-cover | SUBSTITUTED |
| Mutation | scoped `mutmut run` on the 15 changed functions; manual mutants for `install`/`uninstall` | 22 non-equivalent survivors killed by new tests; 3 of 3 manual mutants killed; 18 equivalent survivors named below | SUBSTITUTED |
| Property-based | `tests/test_launchscript.py::test_global_name_round_trips`, 200 examples | holds | PASSED |
| Real execution | branch venv `harnessed install default claude`, then `harnessed-claude-default-container --help`, then `harnessed uninstall default claude`, against a scratch `HOME` | launchers written; `--help` exit 0 with `container-run` usage; bin dir empty after `uninstall`; project dir untouched | PASSED |
| Egress: new data paths | new files in `~/.local/bin` hold only `shlex.join`-quoted stack and harness names; new stderr lines escape their paths with `rich.markup.escape`; nothing leaves the host | bounded and quoted | PASSED |
| Supply chain | new dependencies | none (`hypothesis` already in the dev extra) | PASSED |
| Suite health | pytest-randomly, on in every run | green in randomized order, and twice for the launcher tests | PASSED |
| Live container layer | `live.yml` `live` and `live-docker` | not run; triggers on the PR because `launcher.py` and `paths.py` changed | UNAVAILABLE |
| Adversarial review | `spec-evidence-adversary`, two rounds | round 1: one finding, fixed in `5149831`; round 2: the fix confirmed, one test gap fixed in `2acfc39` | PASSED |

### Layers not run as specified

- SUBSTITUTED — changed-line coverage: whole-project coverage at 80% ran instead. It cannot detect an uncovered changed line inside a file whose total stays above the threshold.
- SUBSTITUTED — mutation: the mutated set was the 15 functions the change adds or alters, not every function in the changed files. `launcher.py` holds thousands of unrelated mutants. mutmut needed a temporary `tests_dir` narrowing and one deselected test (`test_firewall_appends_egress_domains`, which cannot resolve a catalog symlink inside mutmut's copied tree, as `pyproject.toml` documents). That config was restored, uncommitted, after each run. Unchanged functions in those files were not mutated.
- UNAVAILABLE — live container layer: it runs on the pull request. The change touches `launcher.py` and `paths.py`, which are in its trigger list.

Equivalent mutation survivors, named:
- `_write_global_launchers` 7, 9, 12 change only `highlight=`, which affects colour and not the text.
- `_is_retired_shim` 6, 8, `_exec_tokens` 12, 14, `_is_ours_to_touch` 7, 9 and `write_globals` 42, 44, 46 drop or widen a bounded-read limit. That changes memory use on a huge file, never the result.
- `_body` 2, 3, 4, 5, 17, 20 alter `command_for` arguments whose values `_body` discards. It keeps only the flags after `--stack`, and the separator is always present.
- `write_globals` 23, 26, 28 change `zip(strict=...)` over two lists built from the same verbs.
- `write_globals` 56, 58, 60 change the write encoding of an ASCII body.
- `write_globals` 16: `.` is also refused by the third guard clause.
- `rows_referencing` 11 and 39 change a fallback that a later check makes unreachable.

### Defect classes closed

- Generator: a writer or remover in `~/.local/bin` acting on a file harnessed did not write. Sites: `write_globals` (sentinel, directory, symlink: fixed), `remove_globals` (sentinel, symlink: fixed), the `uninstall` shim path (exact exec line match: fixed). `install_stack`'s old unconditional `unlink` is gone.
- Generator: a stack name that resolves to another stack's row or launcher. Sites: `parse_script_name` / `parse_global_name` (read from both ends: already correct, property-tested), `_replays_stack` (exact stack equality: S4.3), `remove_globals` (exact names: S5.1).
- Generator: a report that names something the command did not do. Site: `uninstall`'s row lookup. It used every possible name and now uses only the removed names (adversary round 1). Other report sites, `install` successes and the `uninstall` removal lines, already print only what happened.

### Not reached by review

- The adversary review is bound to `5149831`. `2acfc39` (a test-only commit for S4.4) and `4eb4543` (the `spec-evidence.json` model keys, config only) came after it, so the review layer is not run for those two commits.
- Declined hunch, both rounds: `_body`'s `args.index("--stack")` would raise `ValueError` if `aoe.command_for` ever omitted `--stack`, and `write` catches only `OSError`, so that would escape the launch. It cannot happen today: `command_for` builds `--stack <name>` unconditionally (`src/harnessed/aoe.py:330`), and `TestParityWithCommandFor` pins the shape.

### Agent rounds

| Round | Model | Tokens (in/out) |
|---|---|---|
| Context pack | claude-sonnet-4-6 | 128107/946 |
| Intent review, round 1 | claude-sonnet-4-6 | 47640/238 |
| Intent review, round 2 | claude-sonnet-4-6 | 48015/241 |
| Adversary, round 1 | claude-sonnet-4-6 | 432544/11845 |
| Adversary, round 2 | claude-sonnet-4-6 | 428214/6855 |

All five ran before `spec-evidence.json` set the model keys to `claude-sonnet-5-5` in `4eb4543`. The host default ran.

### Honest notes

- The first baseline run overlapped with the start of RED, and its coverage layer graded a mix of trees. It was discarded. The recorded baseline is a fresh run in a detached worktree of the approval commit `ad8726f`: green, 4056 passed.
- A local launcher now needs its global launcher on the `PATH` that aoe's shell sees, normally `~/.local/bin`. A row whose global launcher is missing fails with "not found" until the next launch or `install` rewrites it. This is the SPEC's Known limit, and `uninstall` names such rows when it removes launchers.
- Existing tests changed: `TestInstallShim` (four tests, replaced; each decision kept or superseded by name in its class docstring), `test_an_ordinary_stack_still_persists`, `TestParityWithCommandFor`, and the five entries of `decisions.md` revision 4. Each keeps the decision it encodes.
