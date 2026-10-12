## Evidence Report — scheduled pin upgrades every other day (Tier 2)

## Summary
**What was delivered, and why.** `tools/pin-upgrade.sh` and `.github/workflows/pin-upgrade.yml` run `harnessed update --yes --no-rebuild` every other day. When a pin moved, the run lands it on `upgrade-<date>` as a GitHub-signed API commit, opens the PR `feat(catalog): upgrade pins <date>`, and dispatches `test.yml` (and `live.yml` when a live trigger file changed). `harnessed update` has a new `--no-rebuild` flag. `pin-check.yml` and its test file are gone, and its trigger rules live on in the new workflow test. Pins now move forward without a manual step, and only when something moved.

**Each criterion and how it was proven.**
- AC-1, nothing eligible means nothing created: S1.1 and S1.3 run the real script against stubs; S1.2 pins the 7.0-day edge in `update`.
- AC-2, one PR of signed API commits: S2.1 to S2.5 read the stub `gh` log, the GraphQL body and the bare `origin`.
- AC-3, a same-day rerun adds to the open PR: S3.1 to S3.5, including the Decide 5 skip after a merge.
- AC-4, checks start: S4.1, S4.2, S4.4, S4.5 read the dispatch calls; S4.3 holds the script's live list equal to `live.yml`.
- AC-5, no prompt and no rebuild: S5.1 and S5.3 through `CliRunner`; S5.4 runs every script test with stdin held open; the real `harnessed update --yes --no-rebuild < /dev/null` finished in 142 s with the skip line.
- AC-6, majors applied: S6.1 to S6.4.
- AC-7, a feat: S7.1 to S7.3.
Every scenario is mapped below and passes. 17 manual mutants were all killed.

**What is not proven.** The workflow has not run on GitHub: it can only be dispatched once it is on `main`. So a GitHub-signed commit, a dispatched `pytest` check that satisfies the ruleset, and a 0.3.0 Release PR are not observed. `live.yml` runs on this PR because `launcher.py` changed, and has not run yet.

**Judgment calls during the build.** S5.1's stub was changed from raising to recording, because `_offer_unpinnable_refresh` turns any exception into a warning and a raising stub hid mutant M2. S7.3 also asserts `bump-patch-for-minor-pre-major` is absent: that setting, not `bump-minor-pre-major`, is what decides that a pre-1.0 `feat` is a minor bump, so the SPEC's sentence names the wrong key as the cause. The adversary's hunches are recorded, not fixed (see Not proven).

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: `tools/pin-upgrade.sh`, `.github/workflows/pin-upgrade.yml`, `harnessed update --no-rebuild`, the deletion of `pin-check.yml`, and 35 new tests.
- Proven: 34/34 scenarios mapped and passing; gauntlet green on 6/6 layers; 17/17 manual mutants killed.
- Not proven: a real run on GitHub (the workflow cannot be dispatched before merge); `live.yml` on this PR (not yet run).

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-12-GH-582/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit 34d1a3f, "GH-582: spec approved")
- Intent review: round 1 changed the SPEC (the Summary's runner sentence reworded; S4.5 and S6.3 added; S2.5 marked a safety guard; Decide 5 added); round 2 changed the SPEC (S6.4 added; a Known limits line on the dispatched `pytest` check)
- Source state: commit 04d6ceadd36fd8e7099ddfae44ab91be13ebbdab — the commit the final gauntlet and adversary round 2 read. The stamp's `dirty: true` comes from untracked files in the story directory only (`baseline-stamp.json`, `findings-code*.md`); no source file was modified.
- Stamp:

```json
{
  "result": "green",
  "expected_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "completed_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "layer_seconds": {"tests": 335.934, "coverage": 350.841, "types": 21.116, "lint": 0.131, "shellcheck": 1.757, "secrets": 2.784},
  "failed": null,
  "exit_code": 0,
  "commit": "04d6ceadd36fd8e7099ddfae44ab91be13ebbdab",
  "dirty": true,
  "written": "2026-10-12T13:19:09.537Z"
}
```

### Spec → Test mapping
`PS` = `tests/test_pin_upgrade_script.py`, `WF` = `tests/test_ci_pin_upgrade_workflow.py`, `UC` = `tests/test_update_cli.py`, `CD` = `tests/test_update_cooldown.py`.

| Scenario | Test | Status |
|---|---|---|
| S1.1 | `PS::TestNothingEligible::test_s1_1_no_change_exits_clean_and_calls_nothing` | pass |
| S1.2 | `CD::TestCooldownWithholdsFreshReleases::test_a_release_exactly_at_the_window_edge_is_offered` | pass |
| S1.3 | `PS::TestNothingEligible::test_s1_3_no_branch_reaches_origin` | pass |
| S2.1 | `PS::TestOneSignedCommitPR::test_s2_1_ref_then_commit_then_pr_in_order` | pass |
| S2.2 | `PS::TestOneSignedCommitPR::test_s2_2_the_commit_carries_the_staged_file` | pass |
| S2.3 | `PS::TestOneSignedCommitPR::test_s2_3_nothing_is_pushed_with_git` | pass |
| S2.4 | `PS::TestOneSignedCommitPR::test_s2_4_two_files_one_commit` | pass |
| S2.5 | `PS::TestOneSignedCommitPR::test_s2_5_a_deletion_is_refused` | pass |
| S3.1 | `PS::TestSameDayRerun::test_s3_1_rerun_stacks_on_the_branch_head` | pass |
| S3.2 | `PS::TestSameDayRerun::test_s3_2_rerun_with_nothing_new_touches_nothing` | pass |
| S3.3 | `PS::TestSameDayRerun::test_s3_3_the_earlier_commit_is_not_rewritten` | pass |
| S3.4 | `PS::TestSameDayRerun::test_s3_4_branch_without_open_pr_gets_one` | pass |
| S3.5 | `PS::TestSameDayRerun::test_s3_5_a_merged_pr_today_skips_the_run` | pass |
| S4.1 | `PS::TestChecksStart::test_s4_1_test_yml_is_dispatched_after_the_commit` (asserts the dispatch list equals `[test.yml]`, so no `live.yml`) | pass |
| S4.2 | `PS::TestChecksStart::test_s4_2_a_live_trigger_file_also_dispatches_live` | pass |
| S4.3 | `WF::TestOneLiveList::test_s4_3_the_script_matches_live_yml` | pass |
| S4.4 | `PS::TestChecksStart::test_s4_4_a_rerun_dispatches_again` | pass |
| S4.5 | `PS::TestChecksStart::test_s4_5_a_failed_dispatch_fails_the_run` | pass |
| S5.1 | `UC::TestUnattendedRun::test_s5_1_no_rebuild_never_reaches_the_runtime` | pass |
| S5.2 | `UC::TestUnpinnableHarnessesAlwaysUpgrade::test_apply_mode_rebuilds_the_unpinnable_image_even_with_nothing_stale` (existing; mutant M16 proves it guards this) | pass |
| S5.3 | `UC::TestUnattendedRun::test_s5_3_a_prompt_with_no_input_fails_instead_of_waiting` | pass |
| S5.4 | `PS::TestNoInput::test_s5_4_harnessed_gets_exactly_these_args_and_no_stdin`, and every `PS` test, which runs the script with stdin held open | pass |
| S6.1 | `UC::TestUnattendedRun::test_s6_1_a_harness_major_lands_with_a_minor` | pass |
| S6.2 | `UC::TestUnattendedRun::test_s6_2_no_pin_is_left_behind` | pass |
| S6.3 | S5.4's test (the arguments are exactly `update --yes --no-rebuild`) | pass |
| S6.4 | `UC::TestUnattendedRun::test_s6_4_a_one_day_old_harness_release_is_applied` | pass |
| S7.1 | `PS::TestFeatTitle::test_s7_1_commit_headline_and_pr_title` | pass |
| S7.2 | `WF::TestFeatRelease::test_s7_2_the_title_passes_pr_title_yml` | pass |
| S7.3 | `WF::TestFeatRelease::test_s7_3_a_feat_is_a_minor_bump_before_1_0` | pass |
| S8.1 | `WF::TestTriggers::test_s8_1_only_schedule_and_dispatch` | pass |
| S8.2 | `WF::TestTriggers::test_s8_2_every_other_day` | pass |
| S8.3 | `WF::TestTheJob::test_s8_3_actions_are_pinned_to_a_sha`, `test_s8_3_bounded_runtime`, `test_s8_3_permissions_are_exactly_these`, `test_s8_3_mise_is_installed_so_registered_tools_resolve` | pass |
| S8.4 | `WF::TestTheJob::test_s8_4_the_script_runs_with_the_workflow_token` | pass |
| S8.5 | `WF::TestTheJob::test_s8_5_pin_check_is_gone_and_tests_still_gate_prs` | pass |

34 scenario lines: S1 3, S2 5, S3 5, S4 5, S5 4, S6 4, S7 3, S8 5. All pass.

### RED record
- First run of the new tests before any code (`tools/run-tests.sh` on the three files): 22 failed, 7 errors, 39 passed. Every failure was a missing script, workflow or flag.
- Passed early, by pre-existing behavior, each then proven with a throwaway mutant: S5.3 (M11), S7.3 (M12), S1.2 (`a >= min_days` → `a > min_days`, killed).
- Passed early because nothing ran yet, then proven: S1.3 (M13), S6.2 (M10).

### Must NOT
| Clause | Proof | Status |
|---|---|---|
| Existing `tests/test_update_*.py` pass unchanged | gauntlet tests layer: 4273 passed, 80 skipped; no existing test edited except the appended class | pass |
| `update` without `--no-rebuild` keeps the rebuild offer | S5.2, mutant M16 killed | pass |
| Release-age constants unchanged | diff: `src/harnessed/update.py` not touched | pass |
| `--check` writes nothing, never rebuilds | existing `test_check_writes_nothing`, `test_check_never_rebuilds` | pass |
| `mise run upgrade-pr` unchanged | diff: `mise.toml` not touched | pass |
| No `git push` in the workflow | S2.3, mutant M13 killed | pass |
| One live list | S4.3, mutant M15 killed | pass |

### Gauntlet
| Layer | Command | Result |
|---|---|---|
| Merge gate parity | `pytest` (test.yml) = tests layer; ruff, pyright, shellcheck (lint.yml) = lint, types, shellcheck layers; `pr-title.yml` regex checked by S7.2; actionlint (not a project gate) run by hand | PASSED |
| Egress: new data paths | the script sends file contents of `catalog/` and `mise.toml` (public repository content) to the GitHub API with `GITHUB_TOKEN`; it logs file paths and the commit oid, never the token | PASSED |
| Full test suite | `mise exec -- tools/run-tests.sh`: 4273 passed, 80 skipped. Baseline collects 4326, HEAD 4353: +35 new, −8 deleted with `test_ci_pin_check_workflow.py` | PASSED |
| Static types | pyright: green | PASSED |
| Lint + format | ruff: green (first run red on S105 and RUF059 in the new tests, fixed in 04d6cea); shellcheck: green; `actionlint` 1.7.7 on `pin-upgrade.yml`: clean | PASSED |
| Changed-line coverage | `pytest --cov=src --cov-branch --cov-fail-under=80`: 86% total. Both branches of the new `if no_rebuild` run (S5.1, S5.2). The shell script is outside `--cov=src`; its branches are covered by the `PS` tests and the mutants below | PASSED |
| Mutation testing | 17 manual mutants (mutmut skips typer commands; the script is shell), all killed: M1 to M17 in `scratchpad/mutants.py`, plus the S1.2 edge mutant. M2 survived once and was killed after the S5.1 test fix | PASSED |
| Property-based tests | no parser, math or serialization changed | N-A |
| Real execution | `XDG_DATA_HOME=<tmp> XDG_CONFIG_HOME=<tmp> mise exec -- uv run --extra dev harnessed update --yes --no-rebuild < /dev/null`: exit 0 in 142 s, `skipped the unpinnable-harness rebuild (--no-rebuild)`, 12 pins bumped across 13 files under `catalog/`, then reverted. The workflow itself: not run (cannot dispatch before merge) | PASSED |
| Supply chain & secrets | gitleaks green; no new dependency; actions pinned to the SHAs other workflows use | PASSED |
| Suite health | randomized order on every run (`pytest-randomly>=3` in the dev extras, `pyproject.toml`); the new tests passed in 4 full-suite runs (the tests and coverage layers of the gauntlet runs on 0389d27 and 04d6cea) and the targeted runs, with no flake | PASSED |
| Adversarial review | round 1 on 0389d27: 0 blocking, 1 advisory finding; round 2 on 04d6cea: 0 findings | PASSED |

### Adversarial review
- Round 1 (`findings-code-round1.md`, commit 0389d27): one advisory finding, that S5.2 and S4.1's "no live.yml" were unguarded. Triage: both already guarded; mutants M16 (skip always) and M17 (live always) were killed by `test_apply_mode_rebuilds_the_unpinnable_image_even_with_nothing_stale` and `test_s4_1_...`. No code change.
- Round 2 (`findings-code.md`, commit 04d6cea): no findings. It ran because 04d6cea came after round 1; that commit only fixed lint in two test files.
- Hunches, recorded, not fixed: no `concurrency` group in the workflow (two overlapping runs make the loser go red, and it may leave a ref); a manual dispatch from a ref other than `main` bases a new branch on that ref; a failed GraphQL commit after the ref is created leaves an empty branch until the next run (S3.4 path); `git fetch` has no credential (works because the repository is public); paths with special characters and file mode changes are not handled (`update` writes ASCII paths and never changes a mode); `git add catalog mise.toml` drops a pin `update` might one day write elsewhere (it writes only under `catalog/` today).

### Agent rounds
| Round | Model | Tokens (in/out) |
|---|---|---|
| Context pack | claude-sonnet-5-5 | 200295/1359 |
| Intent review, round 1 | claude-sonnet-5-5 | 63127/236 |
| Intent review, round 2 | claude-sonnet-5-5 | 63787/234 |
| Adversary, round 1 | claude-sonnet-5-5 | 156854/1056 |
| Adversary, round 2 | claude-sonnet-5-5 | 161802/1219 |

### Not proven
- The workflow on GitHub: a real scheduled or dispatched run, the signed commit, the dispatched `pytest` check satisfying the `main` ruleset, and the 0.3.0 Release PR after the first merge. These are observed after merge.
- `live.yml` on this PR: it triggers on `src/harnessed/launcher.py`, and has not run yet.
- The adversary hunches above.
