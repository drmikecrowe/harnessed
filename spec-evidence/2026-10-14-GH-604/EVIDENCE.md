## Evidence Report — Name the ACP adapter install command of the tool that owns the adapter (Tier 2)

## Summary

**What was delivered, and why.** `harnessed build <stack> claude` and `harnessed host-acp claude` now name the install command of the tool that owns the `claude-agent-acp` on PATH. A mise-owned adapter (installs dir or shim) gets `mise use -g npm:@agentclientprotocol/claude-agent-acp@<pin>`; every other case gets `pnpm add -g @agentclientprotocol/claude-agent-acp@<pin>`. After an install that exits 0, `build` asks PATH again and names a copy that still answers with another version, or says the adapter is not on PATH. Before this, both named `npm i -g`, which a mise or pnpm copy shadowed, so the offer never stopped; raw npm also broke the repo's pnpm rule.

**Each criterion and how it was proven.**
- AC-1, mise: CLI tests drive `build` with a real stub adapter under a temp mise installs dir and a shim, and assert the offer and the `y` argv; subprocess tests run `host-acp claude` and read its stderr line. Both name `mise use -g …` and never `npm i -g`.
- AC-2, no adapter: `build` offers and runs `pnpm add -g …`; `host-acp` refuses with that command. A sweep over five adapter layouts, with and without a terminal, finds no whole-word `npm`/`npx` in any offer, INFO line, warning or refusal, and no install argv that starts with either.
- AC-3, pnpm: a stub `pnpm bin -g` names the dir; the adapter there is classified `pnpm`, and both commands name `pnpm add -g …` with no `mise` and no `npm i -g`. A missing or failing `pnpm` falls back to the same command without failing either command.
- AC-4, after the install: with the stub rewritten to the pin by the install, a second `build` makes no offer, for no-adapter, pnpm, unrecognised and mise setups. With an unrecognised copy still at 0.80.0, `build` names that path and version right after the install.

**What is not proven.** Changed-line coverage ran as total coverage (SUBSTITUTED). Real execution ran the new functions against this host's real mise and pnpm layout, not the CLI entry point (SUBSTITUTED). The adversary read commit `eef8309`; the three later commits change only tests and story files, so the review layer is not-run for them.

**Judgment calls.** The S2.3 check matches `npm`/`npx` as whole words, because `pnpm add -g` is the required command. The mise command skips the re-check (Decide 2 A), and pnpm's dir is what `pnpm bin -g` prints (Decide 1 B). The adversary's two hunches were not acted on; both are recorded below.

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: `build`'s adapter offer and `host-acp`'s adapter messages name `mise use -g` for a mise-owned adapter and `pnpm add -g` otherwise, and `build` re-checks PATH after a successful non-mise install.
- Proven: 19/19 scenarios mapped and passing; 12/12 criterion clauses mapped and passing; 6/6 Must NOT lines mapped and passing.
- Not proven: Changed-line coverage (SUBSTITUTED by total branch coverage); Real execution (SUBSTITUTED by a direct function run on the real host layout); Adversarial review for commits `3f069ca`, `eb998b5`, `89ccd04` (not-run; tests and story files only).

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-14-GH-604/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit `184664c`, "GH-604: spec approved")
- Intent review: round 1 tightened S2.3 to forbid `npm`/`npx` anywhere except the `npm:` spec prefix; round 2 made S5 say the shadow warning fires only off-pin and added S1.5 (no-terminal INFO line for a mise adapter)
- Source state: commit `89ccd04a7f402b027f5fca09dcf07ca1f78b725e` — the commit the final run read; the review read `eef8309`, and `git diff eef8309 89ccd04 -- src` is empty
- Stamp:
```json
{
  "result": "green",
  "expected_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "completed_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "layer_seconds": {"tests": 282.527, "coverage": 325.326, "types": 13.47, "lint": 0.145, "shellcheck": 1.192, "secrets": 2.291},
  "failed": null,
  "exit_code": 0,
  "commit": "89ccd04a7f402b027f5fca09dcf07ca1f78b725e",
  "dirty": false,
  "written": "2026-10-14T12:56:35.272Z"
}
```
- Baseline: baseline-stamp.json at commit `184664ca09a4287dbe66e7c66f2c6fa050006a0a`, green (4570 tests collected)

### Spec → Test mapping

`B` is `tests/test_launcher_build_adapter.py`, `H` is `tests/test_host_acp.py`.

| Scenario | Test | Status |
|---|---|---|
| S1.1 | B::TestS1MiseGetsTheMiseCommand::test_s1_1_a_mise_install_dir_gets_mise_use | pass |
| S1.2 | H::TestTheAdapterCommandFollowsTheOwner::test_s1_2_a_mise_adapter_warns_with_mise_use | pass |
| S1.3 (boundary) | B::TestS1MiseGetsTheMiseCommand::test_s1_3_a_mise_shim_gets_mise_use; H::TestTheAdapterCommandFollowsTheOwner::test_s1_3_a_mise_shim_warns_with_mise_use | pass |
| S1.4 (boundary) | B::TestS1MiseGetsTheMiseCommand::test_s1_4_mise_data_dir_defaults_under_xdg_data_home | pass |
| S1.5 | B::TestS1MiseGetsTheMiseCommand::test_s1_5_no_terminal_names_mise_use_and_runs_nothing | pass |
| S2.1 | B::TestS2NoAdapterGetsPnpm::test_s2_1_no_adapter_gets_pnpm_add; B::TestTheOffer::test_s6_2_yes_runs_the_install | pass |
| S2.2 | H::TestTheAdapterAtLaunch::test_s6_8_a_missing_adapter_refuses_on_stderr | pass |
| S2.3 (negative) | B::TestS2NoAdapterGetsPnpm::test_s2_3_no_message_names_raw_npm (10 cases); B::TestS2NoAdapterGetsPnpm::test_s2_3_no_install_runs_npm_or_npx (5 cases); H::TestTheAdapterCommandFollowsTheOwner::test_s2_3_no_adapter_line_names_raw_npm (5 cases) | pass |
| S3.1 | B::TestS3PnpmGetsPnpm::test_s3_1_a_pnpm_global_bin_gets_pnpm_add; H::TestTheAdapterCommandFollowsTheOwner::test_s3_1_a_pnpm_adapter_warns_with_pnpm_add | pass |
| S3.2 (boundary) | B::TestS3PnpmGetsPnpm::test_s3_2_no_pnpm_on_path_is_unrecognised | pass |
| S3.3 (negative) | B::TestS3PnpmGetsPnpm::test_s3_3_a_failing_pnpm_bin_is_unrecognised; H::TestTheAdapterCommandFollowsTheOwner::test_s3_3_a_failing_pnpm_bin_still_warns_with_pnpm_add | pass |
| S3.4 (boundary) | B::TestS3PnpmGetsPnpm::test_s3_4_mise_and_no_adapter_never_ask_pnpm[mise], [none] | pass |
| S4.1 | B::TestS4UnrecognisedFallsBackToPnpm::test_s4_1_an_unrecognised_dir_gets_pnpm_add; H::TestTheAdapterCommandFollowsTheOwner::test_s4_1_an_unrecognised_adapter_warns_with_pnpm_add | pass |
| S5.1 | B::TestS5TheVersionIsCheckedAgain::test_s5_1_a_working_install_ends_the_offer[none], [pnpm], [other] | pass |
| S5.2 (negative) | B::TestS5TheVersionIsCheckedAgain::test_s5_2_a_shadowing_copy_is_named_with_its_version | pass |
| S5.3 (boundary) | B::TestS5TheVersionIsCheckedAgain::test_s5_3_the_mise_command_is_not_checked_again | pass |
| S5.4 (boundary) | B::TestS5TheVersionIsCheckedAgain::test_s5_4_a_typed_command_is_checked_again | pass |
| S5.5 (negative) | B::TestS5TheVersionIsCheckedAgain::test_s5_5_a_failed_install_is_not_checked_again; B::TestTheOffer::test_s6_6_a_failed_install_warns_and_builds_on | pass |
| S5.6 (negative) | B::TestS5TheVersionIsCheckedAgain::test_s5_6_an_install_that_lands_off_path_says_so | pass |
| Must NOT: failed or shadowed install never fails build | B::TestTheOffer::test_s6_6_a_failed_install_warns_and_builds_on; B::…::test_s5_2, ::test_s5_5, ::test_s5_6 (each asserts exit 0) | pass |
| Must NOT: host-acp never prompts, stdout clean | H::TestTheAdapterCommandFollowsTheOwner::test_s1_2_a_mise_adapter_warns_with_mise_use (stdout `b""`); H::TestTheAdapterAtLaunch::test_s6_8_a_missing_adapter_refuses_on_stderr | pass |
| Must NOT: omp never checks the adapter | B::TestTheOffer::test_s6_9_omp_never_checks_the_adapter | pass |
| Must NOT: pin read from the catalog | B and H read `launcher._acp_adapter_pin()`; no literal pin in either file's assertions | pass |
| Must NOT: `c` runs the typed command through bash | B::TestTheOffer::test_s6_3_c_runs_the_typed_command_through_bash | pass |
| Must NOT: no terminal names the command and runs nothing | B::TestTheOffer::test_s6_7_no_terminal_asks_nothing_and_names_the_command; B::…::test_s1_5 | pass |
| AC-1 condition: mise adapter at a non-pin version, offer and warning name `mise use -g …@0.89.1` | B::TestS1MiseGetsTheMiseCommand::test_s1_1_a_mise_install_dir_gets_mise_use; H::TestTheAdapterCommandFollowsTheOwner::test_s1_2_a_mise_adapter_warns_with_mise_use | pass |
| AC-1 boundary: installs dir or `shims/claude-agent-acp` | B::…::test_s1_1; B::…::test_s1_3_a_mise_shim_gets_mise_use; H::…::test_s1_3_a_mise_shim_warns_with_mise_use | pass |
| AC-1 negative: neither message names `npm i -g` | B::…::test_s1_1 (asserts `npm i -g` absent); H::…::test_s1_2 (asserts `npm i -g` absent) | pass |
| AC-2 condition: no adapter, offer and refusal name `pnpm add -g …@0.89.1` | B::TestS2NoAdapterGetsPnpm::test_s2_1_no_adapter_gets_pnpm_add; H::TestTheAdapterAtLaunch::test_s6_8_a_missing_adapter_refuses_on_stderr | pass |
| AC-2 boundary: no `claude-agent-acp` on PATH | B::…::test_s2_1 (PATH is an empty dir); H::…::test_s6_8 (PATH stripped of every dir holding it) | pass |
| AC-2 negative: no message on any path names raw npm | B::…::test_s2_3_no_message_names_raw_npm (10 cases); B::…::test_s2_3_no_install_runs_npm_or_npx (5 cases); H::…::test_s2_3_no_adapter_line_names_raw_npm (5 cases) | pass |
| AC-3 condition: pnpm adapter at a non-pin version, both name `pnpm add -g …@0.89.1` | B::TestS3PnpmGetsPnpm::test_s3_1_a_pnpm_global_bin_gets_pnpm_add; H::TestTheAdapterCommandFollowsTheOwner::test_s3_1_a_pnpm_adapter_warns_with_pnpm_add | pass |
| AC-3 boundary: the adapter lives under pnpm's global bin dir | B::…::test_s3_1 (classified `pnpm`); B::…::test_s3_2, ::test_s3_3 (outside a known pnpm dir, classified `other`) | pass |
| AC-3 negative: neither message names `npm` or `mise` | B::…::test_s3_1 and H::…::test_s3_1 (assert `mise` and `npm i -g` absent); B::…::test_s2_3_no_message_names_raw_npm[*-pnpm] and H::…::test_s2_3_no_adapter_line_names_raw_npm[pnpm] (no whole-word `npm`) | pass |
| AC-4 condition: mise, pnpm and no-adapter cases, next build makes no offer after the command exits 0 | B::TestS5TheVersionIsCheckedAgain::test_s5_1_a_working_install_ends_the_offer[none], [pnpm], [other]; B::…::test_s5_3_the_mise_command_is_not_checked_again | pass |
| AC-4 boundary: `--version` now reports 0.89.1 | B::…::test_s5_1 and ::test_s5_3 (the stub on PATH reports the pin before the second build) | pass |
| AC-4 negative: an unrecognised copy still first at another version, build re-checks and prints its path and version | B::…::test_s5_2_a_shadowing_copy_is_named_with_its_version; B::…::test_s5_4_a_typed_command_is_checked_again | pass |

Break checks. Every new test that failed on the approval code is in RED commit `a78a75e` (33 build tests and 10 host tests failed, each on the old `npm i -g` text). Seven passed before the change. Six of them were each broken by a throwaway mutant, then restored:
- S3.4[mise], pnpm asked before the mise check: failed. S3.4[none] has no mutant; an absent adapter returns before pnpm is asked.
- S5.1 ×3, the re-check warns unconditionally: all 3 failed.
- S5.5, no `return` after the failed-install warning: failed.
- H S3.3, a failing `pnpm bin -g` raises: failed.

The corrected S2.3 check failed on the original `launcher.py` (20 cases).

### Gauntlet (final fresh run)
| Layer | Command | Status + result | Log |
|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4534 passed, 80 skipped (baseline 4570 collected; now 4614 collected, +44 new) | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 86.61% total; `src/harnessed/launcher.py` 71% | work/coverage.log |
| types | `pyright --pythonpath <venv python>` | PASSED — 0 errors, 0 warnings | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — All checks passed | work/lint.log |
| shellcheck | `shellcheck $(git ls-files "*.sh")` | PASSED — exit 0, no findings (no shell change) | work/shellcheck.log |
| secrets | `gitleaks detect --no-banner --redact` | PASSED — no leaks found | work/secrets.log |
| Real execution | `uv run python -c` calling `_acp_adapter_owner`, `_pnpm_global_bin`, `_installed_acp_adapter` and `_acp_adapter_install_cmd` on this host's real PATH | SUBSTITUTED — owner `mise` for `~/.local/share/mise/installs/npm-agentclientprotocol-claude-agent-acp/0.89.1/bin/claude-agent-acp`; `pnpm bin -g` answered `~/.local/share/pnpm/bin`; command `mise use -g npm:@agentclientprotocol/claude-agent-acp@0.89.1` | /tmp/gh604/real-exec.log |
| Adversarial review | `spec-evidence-adversary`, 1 round on `184664c...eef8309` | PASSED — 0 findings, 2 hunches (not acted on, see Honest notes); no code changed after it, so no round 2 | findings-code.md |
| Merge gate parity | lint.yml (ruff, pyright, shellcheck) and test.yml (pytest) map to lint, types, shellcheck, tests | PASSED for those; `live.yml` triggers on `src/harnessed/launcher.py` and runs on the PR | — |
| Egress: new data paths | review of the new stderr lines | PASSED — the shadow warning prints the path `shutil.which` found on the user's own PATH and the version it printed; both go to stderr, are bounded to one line, and carry no secret | — |
| Suite health | `tools/run-tests.sh` runs pytest-randomly by default | PASSED — the final run is in random order, 0 failures | work/tests.log |
| Supply chain & secrets | `git diff 184664c 89ccd04` adds no dependency; gitleaks above | PASSED — 0 new dependencies | — |

### Layers not run as specified
- N-A: Mutation testing — not a declared layer in `tools/gauntlet-layers.json`, and Tier 2 does not require it; the targeted throwaway mutants above ran instead for the pre-passing tests.
- N-A: Property-based tests — no parser, math or serialization changed.
- SUBSTITUTED: Changed-line coverage — total branch coverage ran (86.61%, threshold 80%); it cannot detect a changed line no test executes.
- SUBSTITUTED: Real execution — the new functions ran against the real host layout; it cannot detect CLI wiring faults, which the CliRunner `build` tests and the subprocess `host-acp` tests cover. `build` and `host-acp` were not run live: AGENTS.md reserves `host-acp` for the user, and a live `build` rewrites the shared runtime profiles.

### Defect classes closed
- Generator: a host-side message or command in `src/` that tells the user to run, or runs, raw `npm`/`npx`.
- Enumerated by: `grep \bnp[mx]\b` over `src/harnessed` (55 matching lines in 10 files)
- Sites: 1 — `src/harnessed/launcher.py` `_acp_adapter_install_cmd` — fixed. The other 54 lines are not applicable: the BLD-03 lint and its pnpm mapping table (`schema.py`), comments, mise `npm:` backend specs (`update.py`, `hostrun.py`, `toollock.py`, `emit.py`, `mounts.py`), and the `_installed_acp_adapter` docstring describing npm's install layout. None tells the user to run npm.

### Not reached by review
- Round 1: calls 4/10; hunts not reached: 1 (merge-gate argument comparison: the workflows and tools/gauntlet-layers.json were not opened), 8 (no EVIDENCE report in the diff), 9 (the real layout of mise's npm backend installs dir was not verified); sites not opened: tests/test_host_acp.py: the host fixture and its path_prefix handling, /home/mcrowe/Programming/Personal/harnessed/worktrees/GH-604/.github/workflows/test.yml, lint.yml, live.yml

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 92708/434 |
| spec-evidence-intent | 1 | claude-sonnet-5-5 | 59736/228 |
| spec-evidence-intent | 2 | claude-sonnet-5-5 | 60467/230 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 186184/1248 |

### Honest notes
- The first post-GREEN gauntlet was red on types: pyright flagged an Optional stub dir in the new S3.1 test. Fixed in `3f069ca` with a not-None guard; no assertion changed.
- The first GREEN run failed 9 S2.3 cases because the check matched the substring `npm` inside `pnpm`. Fixed in `54879b6` to whole words; the fixed check still fails on the original code.
- While mapping, S3.3's host-acp half had no test. Added in `89ccd04` and broken by a mutant before the final run.
- Adversary hunch 1: a mise layout outside `$MISE_DATA_DIR/{installs,shims}` (a custom shims or installs dir, or a relative or `~` `MISE_DATA_DIR`) is classified `other` and gets `pnpm add -g`, which the mise copy can shadow. Not fixed: the SPEC defines the mise location as those two dirs. S5.2's re-check names the shadowing copy. The real layout on this host is recognised (Real execution row), which also covers the adversary's unreached hunt 9.
- Adversary hunch 2: `pnpm bin -g` (10 s timeout) can run on host-acp's off-pin warning path. Accepted under Decide 1 B and listed in SPEC Known limits.
- The review layer binds to `eef8309`. Commits `3f069ca`, `eb998b5` and `89ccd04` came after it; they change tests and story files only (`git diff eef8309 89ccd04 -- src` is empty).
- The Gortex MCP server failed to connect this session; code was read with the atlas_code tools and native Read on the worktree.
