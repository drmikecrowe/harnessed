## Evidence Report — Copy ~/.claude/CLAUDE.md @-imports into stack rules for ACP sessions (Tier 2)

## Summary

**What was delivered, and why.** `host-acp` and `container-acp` sessions now get the files that `~/.claude/CLAUDE.md` pulls in with `@`-imports. The ACP adapter expands none of them, and on 2026-10-14 that was still true on the pinned claude-agent-acp 0.89.1. With the user's per-stack consent, harnessed keeps a real copy of each import in `rules/harnessed-imports/` and rewrites it on every launch:
- On the host, the launch plan syncs the copies into the stack's config dir.
- In a container, the copies are mounted read-only.

**The acceptance criteria, and how each was proven.**
- **AC-1, who asks:** unit tests drive `build`, `install`, `host-run` and `container-run` through the CLI. Other tests show that a project or parent CLAUDE.md, or a file with no import, asks nothing. Live, the engineer's `harnessed build hostspike claude` in a real terminal asked the exact prompt and stored `y`.
- **AC-2, the copy reaches the session:** proven live in both modes. With a stored `y`, a fresh `host-acp` session and a fresh `container-acp` session (docker) each quoted text that exists only in `active.md`; without the change, the same probe returned `NOT LOADED`. Unit tests show the copy is a regular file, and that the container mount is composed. Inside the running container the mount is read-only and the copy is byte-identical to `active.md`.
- **AC-3, the copy refreshes:** proven live. After `gortex instructions switch localization`, a new `host-acp` session quoted the localization-only line. A unit test shows the copy refreshes on a launch where the stack fingerprint is unchanged.
- **AC-4, the warning:** a real `host-acp` process prints the warning on stderr, and its stdout parses as JSON-RPC only. Unit tests cover `n`, `y`, `i` and no import.
- **AC-5, the answer is stored per stack:** unit tests.
- **AC-6, deletion:** unit tests show that a removed import, or `--reask-imports` answered `n` or `i`, deletes the copy. A user's own rule beside it survives.
- **AC-7, bad imports:** unit tests show that a missing target warns and is skipped, and that a nested import is copied as text. Two imports with the same file name get distinct copies.

**What is not proven.**
- Changed-line coverage and mutation testing were substituted. Total branch coverage ran instead of a changed-line gate, and five hand-made mutants ran instead of a mutation tool.

**Judgment calls made during the build.**
- The host adapter was moved from 0.85.1 to the 0.89.1 pin with mise, with the engineer's yes, so step 0 tested the version the container ships.
- The container probe ran on docker, not podman (this machine has no podman). Its first try failed with `Authentication required`: the container's copy of the Claude credentials was rejected, a harnessed credential problem outside this story. The engineer logged in inside the container by hand, and the rerun passed.
- The first baseline was discarded. It ran in the working tree while the new module was being written. It was rerun in a detached worktree of the approval commit.
- Adversary round 1 had two hunches confirmed and fixed: `host-exec` could prompt, and a write error could fail a launch. Round 2 confirmed nothing.

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: whole-line `@`-imports in `~/.claude/CLAUDE.md` reach `host-acp` (proven live) and `container-acp` (mount proven by unit test) as real copies in a harnessed-owned `rules/harnessed-imports/`, behind a per-stack y/n/i answer.
- Proven: 31 of 31 scenarios mapped and passing.
- Not proven: changed-line coverage (SUBSTITUTED by total branch coverage); mutation testing (SUBSTITUTED by 5 throwaway mutants); merge-gate `live.yml` (runs on the PR, not yet run).

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-14-GH-600/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit 267ff1d, `GH-600: spec approved`)
- Intent review: round 1 added S3.4 (the container refresh step) and a step-0 live check that ACP loads a rules subdirectory; round 2 added S7.4 (no target is read without a `y`).
- Source state: commit 1f5572c0bc55453ed4a8de3000e58b9211998ea9 — the commit the final run read; adversary round 2 read fe23b15, and 1f5572c adds only the round-2 record under `spec-evidence/`. Every later commit changes only files under `spec-evidence/2026-10-14-GH-600/`, so no source changed after this run.
- Stamp:

```json
{
  "result": "green",
  "expected_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "completed_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "layer_seconds": {"tests": 323.184, "coverage": 318.527, "types": 12.801, "lint": 0.107, "shellcheck": 1.422, "secrets": 2.169},
  "failed": null,
  "exit_code": 0,
  "commit": "1f5572c0bc55453ed4a8de3000e58b9211998ea9",
  "dirty": false,
  "written": "2026-10-14T01:38:11.937Z"
}
```

- Baseline: baseline-stamp.json at commit 267ff1d05f32ba2eda71729818ee1f0a19279cfc, green (4418 passed, 80 skipped; coverage 86%)

### Spec → Test mapping

`CI` is `tests/test_claude_imports.py`, `LH` is `tests/test_launch_host.py`. Live logs are under the story directory's `work/` (gitignored); their replies are quoted in Honest notes.

| Scenario | Test | Status |
|---|---|---|
| S1.1 | CI::TestS1WhoAsks::test_s1_1_ask_shows_the_story_prompt_and_stores_the_answer; CI::TestS1WhoAsks::test_s1_1_an_answer_outside_y_n_i_is_asked_again; CI::TestS1TheFourCommandsAsk::test_s1_1_build; ::test_s1_1_install; ::test_s1_1_host_run; ::test_s1_1_container_run; ::test_s1_1_build_for_another_harness_does_not_ask | pass |
| S1.2 (boundary) | CI::TestS1WhoAsks::test_s1_2_an_import_outside_the_user_claude_md_is_never_asked_about[project], [parent] | pass |
| S1.3 (negative) | CI::TestS1WhoAsks::test_s1_3_no_import_means_no_question_and_no_answer (2 cases) | pass |
| S1.4 (negative) | CI::TestS1WhoAsks::test_s1_4_a_mid_line_at_sign_is_not_an_import (5 cases); CI::TestImportGrammar::test_a_bare_at_sign_is_not_an_import | pass |
| S1.5 (negative) | CI::TestS1WhoAsks::test_s1_5_no_terminal_means_no_question; ::test_s1_5_acp_mode_means_no_question_even_with_a_tty; ::test_s1_5_the_exec_verbs_cannot_prompt; CI::TestS1TheFourCommandsAsk::test_s1_5_host_exec_never_reaches_the_question | pass |
| S2.1 | CI::TestS2CopiesAndTheMount::test_s2_1_y_writes_a_regular_file_with_the_target_bytes; LH::TestClaudeImportsOnTheHostPlan::test_s2_1_the_plan_writes_a_regular_copy; CI::TestS4HostAcpProcess::test_s2_1_host_acp_with_yes_lands_the_copy_in_the_config_dir | pass |
| S2.2 | CI::TestS2CopiesAndTheMount::test_s2_2_the_mount_is_composed_after_the_config_volume; ::test_s2_2_no_mount_without_a_yes (3 cases); ::test_s2_2_another_harness_gets_no_mount | pass |
| S2.3 (live) | live: `tools/acp-smoke.py --verb host-acp --harness claude --stack hostspike --prompt …` with a stored `y`, claude-agent-acp 0.89.1 — log `work/s23.log` | pass |
| S2.4 (live) | live: `tools/acp-smoke.py --verb container-acp --harness claude --stack hostspike --prompt …` on docker, after `y` — log `work/s24.log`; mount check `work/s24-mount.log` | pass |
| S2.5 (negative) | CI::TestS2CopiesAndTheMount::test_s2_5_no_answer_creates_no_owned_dir; live step-0 probe A (`work/probe-a.log`, reply `NOT LOADED`) | pass |
| S3.1 | LH::TestClaudeImportsOnTheHostPlan::test_s3_1_an_unchanged_stack_still_gets_the_new_content | pass |
| S3.2 (live) | live: `gortex instructions switch localization`, then the same probe for the localization-only line, then switch back to `core` — log `work/s32.log` | pass |
| S3.3 (boundary) | CI::TestS3Refresh::test_s3_3_a_refresh_keeps_the_copies_dir_itself | pass |
| S3.4 | CI::TestS3Refresh::test_s3_4_container_materialize_refreshes_and_prunes_first | pass |
| S4.1 | CI::TestS4AcpWarning::test_s4_1_s4_2_no_answer_or_n_warns_on_stderr_only[None]; CI::TestS4HostAcpProcess::test_s4_1_host_acp_warns_on_stderr_and_stdout_stays_json_rpc | pass |
| S4.2 | CI::TestS4AcpWarning::test_s4_1_s4_2_no_answer_or_n_warns_on_stderr_only[n] | pass |
| S4.3 (negative) | CI::TestS4AcpWarning::test_s4_3_y_or_i_is_silent (2 cases) | pass |
| S4.4 (negative) | CI::TestS4AcpWarning::test_s4_4_no_import_is_silent (4 cases) | pass |
| S5.1 | CI::TestS5StoredPerStack::test_s5_1_the_answer_is_stored_and_not_asked_again (3 cases) | pass |
| S5.2 (boundary) | CI::TestS5StoredPerStack::test_s5_2_another_stack_still_asks | pass |
| S5.3 (negative) | CI::TestS5StoredPerStack::test_s5_3_n_or_i_copies_nothing (2 cases) | pass |
| S5.4 (negative) | CI::TestS5StoredPerStack::test_s5_4_a_junk_answer_file_counts_as_no_answer (4 cases) | pass |
| S6.1 | CI::TestS6DeletesOnlyItsOwn::test_s6_1_a_removed_import_loses_its_copy | pass |
| S6.2 | CI::TestS6DeletesOnlyItsOwn::test_s6_2_reask_answered_n_or_i_removes_the_copies (2 cases); CI::TestS1TheFourCommandsAsk::test_s6_2_build_reask_imports_passes_reask | pass |
| S6.3 (negative) | CI::TestS6DeletesOnlyItsOwn::test_s6_3_reask_answered_y_deletes_nothing | pass |
| S6.4 (negative) | CI::TestS6DeletesOnlyItsOwn::test_s6_4_a_user_rule_beside_the_owned_dir_survives_every_sync | pass |
| S6.5 (boundary) | CI::TestS6DeletesOnlyItsOwn::test_s6_5_reask_with_no_terminal_clears_and_warns; ::test_s6_5_build_reask_with_no_terminal_exits_0 | pass |
| S7.1 | CI::TestS7MissingAndNested::test_s7_1_a_missing_target_warns_and_the_rest_is_copied; ::test_s7_1_a_sync_whose_only_target_is_missing_does_not_raise | pass |
| S7.2 (boundary) | CI::TestS7MissingAndNested::test_s7_2_a_nested_import_is_copied_as_text_and_not_followed | pass |
| S7.3 (boundary) | CI::TestS7MissingAndNested::test_s7_3_same_name_different_dirs_get_distinct_copies_and_duplicates_one | pass |
| S7.4 (negative) | CI::TestS7MissingAndNested::test_s7_4_without_a_yes_no_target_is_read_and_nothing_warns (3 cases) | pass |

Story criteria, clause by clause:

| Criterion clause | Test | Status |
|---|---|---|
| AC-1 condition: the four commands ask the quoted prompt | CI::TestS1WhoAsks::test_s1_1_ask_shows_the_story_prompt_and_stores_the_answer; CI::TestS1TheFourCommandsAsk::test_s1_1_build, ::test_s1_1_install, ::test_s1_1_host_run, ::test_s1_1_container_run; live `harnessed build hostspike claude` in a terminal printed the prompt (quoted in Honest notes) | pass |
| AC-1 boundary: only `~/.claude/CLAUDE.md` imports count | CI::TestS1WhoAsks::test_s1_2_an_import_outside_the_user_claude_md_is_never_asked_about | pass |
| AC-1 negative: no import, no question | CI::TestS1WhoAsks::test_s1_3_no_import_means_no_question_and_no_answer | pass |
| AC-2 condition: host-acp returns the marker after `y` | live S2.3 (`work/s23.log`); CI::TestS4HostAcpProcess::test_s2_1_host_acp_with_yes_lands_the_copy_in_the_config_dir | pass |
| AC-2 condition: container-acp returns the marker after `y` | live S2.4 (`work/s24.log`); CI::TestS2CopiesAndTheMount::test_s2_2_the_mount_is_composed_after_the_config_volume | pass |
| AC-2 boundary: the copy is a regular file, not a symlink | CI::TestS2CopiesAndTheMount::test_s2_1_y_writes_a_regular_file_with_the_target_bytes; LH::TestClaudeImportsOnTheHostPlan::test_s2_1_the_plan_writes_a_regular_copy | pass |
| AC-2 negative: before the answer, no marker | live step-0 probe A (`work/probe-a.log`); CI::TestS2CopiesAndTheMount::test_s2_5_no_answer_creates_no_owned_dir | pass |
| AC-3 condition: after `gortex instructions switch`, the new marker | live S3.2 (`work/s32.log`); LH::TestClaudeImportsOnTheHostPlan::test_s3_1_an_unchanged_stack_still_gets_the_new_content | pass |
| AC-3 boundary: rewritten on every launch, not only at build | LH::TestClaudeImportsOnTheHostPlan::test_s3_1_an_unchanged_stack_still_gets_the_new_content (`rebuilt is False`); CI::TestS3Refresh::test_s3_4_container_materialize_refreshes_and_prunes_first | pass |
| AC-3 negative: a session started before the switch need not change | no behaviour to test: the clause grants a permission | n-a |
| AC-4 condition: no answer or `n` warns on stderr | CI::TestS4AcpWarning::test_s4_1_s4_2_no_answer_or_n_warns_on_stderr_only; CI::TestS4HostAcpProcess::test_s4_1_host_acp_warns_on_stderr_and_stdout_stays_json_rpc | pass |
| AC-4 boundary: no stdout byte | CI::TestS4HostAcpProcess::test_s4_1_host_acp_warns_on_stderr_and_stdout_stays_json_rpc; CI::TestS4AcpWarning::test_s4_1_s4_2_no_answer_or_n_warns_on_stderr_only (`out == ""`) | pass |
| AC-4 negative: `y` or `i` is silent | CI::TestS4AcpWarning::test_s4_3_y_or_i_is_silent | pass |
| AC-5 condition: stored per stack, not asked again | CI::TestS5StoredPerStack::test_s5_1_the_answer_is_stored_and_not_asked_again | pass |
| AC-5 boundary: another stack still asks | CI::TestS5StoredPerStack::test_s5_2_another_stack_still_asks | pass |
| AC-5 negative: `n` or `i` copies nothing | CI::TestS5StoredPerStack::test_s5_3_n_or_i_copies_nothing | pass |
| AC-6 condition: removed import, or `--reask-imports` answered `n`/`i`, deletes the copy | CI::TestS6DeletesOnlyItsOwn::test_s6_1_a_removed_import_loses_its_copy; ::test_s6_2_reask_answered_n_or_i_removes_the_copies; CI::TestS1TheFourCommandsAsk::test_s6_2_build_reask_imports_passes_reask | pass |
| AC-6 boundary: only harnessed's own copies are deleted | CI::TestS6DeletesOnlyItsOwn::test_s6_4_a_user_rule_beside_the_owned_dir_survives_every_sync | pass |
| AC-6 negative: a user rule is never deleted; `y` deletes nothing | CI::TestS6DeletesOnlyItsOwn::test_s6_4_a_user_rule_beside_the_owned_dir_survives_every_sync; ::test_s6_3_reask_answered_y_deletes_nothing | pass |
| AC-7 condition: a missing target warns with its path, launch goes on | CI::TestS7MissingAndNested::test_s7_1_a_missing_target_warns_and_the_rest_is_copied | pass |
| AC-7 boundary: a nested import is copied as text, not followed | CI::TestS7MissingAndNested::test_s7_2_a_nested_import_is_copied_as_text_and_not_followed | pass |
| AC-7 negative: a missing target never fails build or a launch | CI::TestS7MissingAndNested::test_s7_1_a_sync_whose_only_target_is_missing_does_not_raise; ::test_must_not_an_unwritable_copies_dir_warns_and_does_not_raise | pass |

Must NOT lines: `~/.claude/CLAUDE.md` and targets never written — CI::TestImportGrammar::test_the_import_file_is_never_written; imports never enter the fingerprint — LH::TestClaudeImportsOnTheHostPlan::test_imports_never_enter_the_fingerprint (passed before the change: kept as regression armour); no stdout byte under ACP — the S4.1 process test; no prompt without a terminal — S1.5 rows; no launch failure over an import — the AC-7 negative row; existing tests — the full suite, 4490 passed against 4418 at baseline, none failing.

### Gauntlet (final fresh run)
| Layer | Command | Status + result | Log |
|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4490 passed, 80 skipped (baseline 4418 passed, 80 skipped; +72 = 71 new tests + 1 new ledger case) | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 87% total (baseline 86%); `src/harnessed/claude_imports.py` 97% | work/coverage.log |
| types | `pyright --pythonpath <venv python>` | PASSED — 0 errors, 0 warnings | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — All checks passed | work/lint.log |
| shellcheck | `shellcheck $(git ls-files "*.sh")` | PASSED — exit 0 | work/shellcheck.log |
| secrets | `gitleaks detect --no-banner --redact` | PASSED — no leaks found | work/secrets.log |
| Real execution | `tools/acp-smoke.py --harness claude --stack hostspike --prompt …`: `--verb host-acp` (S2.3, S3.2, step-0 probes A and B) and `--verb container-acp` on docker (S2.4); `harnessed build hostspike claude` in a terminal (AC-1) | PASSED — 6 live runs, each as expected, stdout JSON-RPC only | story dir `work/*.log` |
| Adversarial review | `spec-evidence-adversary`, 2 rounds | PASSED — round 1: 0 findings, 2 hunches confirmed and fixed (784b089); round 2: 0 findings, 0 confirmed | findings-code-round1.md, findings-code.md |
| Merge gate parity | lint.yml (ruff, pyright, shellcheck) and test.yml (pytest) map to lint, types, shellcheck, tests | PASSED for those; `live.yml` triggers on `launcher.py` and `paths.py` and runs on the PR | — |

### Layers not run as specified
- SUBSTITUTED: Changed-line coverage — total branch coverage ran (`--cov-fail-under=80`); it cannot show that each changed line in `launcher.py` ran. The new module alone is at 97%.
- SUBSTITUTED: Mutation testing — no mutation tool is a declared layer; 5 throwaway mutants ran by hand over `claude_imports.py` and `launcher.py` (`work/` script), all killed after one test input was added. It cannot detect what a tool's mutant set would.
- N-A: Property-based tests — Tier 2; loop.md requires them at Tier 3.
- N-A: Suite health, randomized order — not a declared layer; the suite ran in its default order twice (tests, coverage), both green.
- Egress: new data paths — the copies carry the user's own imported instruction files into the stack's config dir and, read-only, into the stack's container. Source: files the user's own `~/.claude/CLAUDE.md` names. Bounded by the user's `y`. Nothing is logged except a missing path in a warning.

### Defect classes closed
- Generator: a call to `claude_imports.ask` reached before an exec or ACP verb declares its mode.
- Enumerated by: `rg -n 'claude_imports\.ask\(' src/harnessed/launcher.py`
- Sites: 4 — `host_run` fixed (784b089); `container_run` already correct (sets exec and ACP mode on its first lines); `build` and `install_stack` not applicable (no exec verb).
- Generator: a filesystem write on the copy path that is not guarded.
- Enumerated by: reading every write in `src/harnessed/claude_imports.py` (`mkdir`, `write_bytes`, `copyfile`, `rmtree`, `unlink`).
- Sites: 3 — `refresh` fixed (784b089); `sync_owned_dir` fixed (784b089); the answer-file write and unlink not applicable (harnessed's state dir, which every launch already needs).

### Not reached by review
- Round 1: calls 3/10; hunts not reached: 1 (merge-gate argument comparison: test.yml, lint.yml, live.yml and tools/gauntlet-layers.json not opened), 2 (call sites of changed functions outside the diff: _host_launch_plan, materialize_config, host_acp, install_stack), 3 (I did not enumerate other users of the config dir's rules/ that might clash with harnessed-imports), 9 (not confirmed: console._can_prompt, in_acp_mode, _CONTAINER_HOME_STR and set_exec_mode exist and behave as assumed); sites not opened: /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/src/harnessed/console.py (_can_prompt, in_acp_mode), /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/src/harnessed/launcher.py:3634 (host_run) and :4410 (container_run) for the order of exec-mode and ACP-mode setup relative to ask(), /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/.github/workflows/test.yml, lint.yml and live.yml, /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/tools/gauntlet-layers.json
- Round 2: calls 6/10; hunts not reached: 2 (call sites of _host_launch_plan, ContainerBackend.materialize_config, host_acp and install_stack outside the diff: not enumerated, because Grep and Read on indexed source were blocked by the Gortex hook and the Gortex MCP tools are not callable by me), 9 (console._can_prompt, in_acp_mode, in_exec_mode and set_exec_mode: existence and behavior unverified; I relied on decisions.md and the tests' use of them), 1 (test.yml and live.yml not opened); sites not opened: /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/src/harnessed/console.py, /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/src/harnessed/launcher.py:2600-2640 (_host_launch_plan body and its callers), /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/src/harnessed/launcher.py:3634 (host_run signature), /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/6-3-gh-600-claude-md-imports-to-rules/.github/workflows/live.yml

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 155836/1086 |
| spec-evidence-intent | 1 | claude-sonnet-5-5 | 60799/231 |
| spec-evidence-intent | 2 | claude-sonnet-5-5 | 61007/254 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 154693/1035 |
| spec-evidence-adversary | 2 | claude-sonnet-5-5 | 215291/2015 |

### Honest notes
- S2.4, verbatim, from a `container-acp` session on docker: `Inactive ref/commit views are immutable committed structural/source snapshots: no working-copy LSP, \`search.text\`, or edits.` The agent added: `It comes from /home/harnessed/.claude/rules/harnessed-imports/active-44be1670.md, in the "Worktree and branch routing" section.` In the running container (`work/s24-mount.log`): the copies dir is mounted at `/home/harnessed/.claude/rules/harnessed-imports` with `rw=false`, a write fails with `Read-only file system`, the copy's sha256 equals `active.md`'s (`3bb59790…`), and the adapter is 0.89.1. The run used docker; podman is not installed here.
- AC-1 live: the engineer's `harnessed build hostspike claude` in a real terminal printed `Your ~/.claude/CLAUDE.md uses @import syntax that ACP sessions do not expand. Copy the imported files into this stack's rules? [y/n/i]`, answered `y`. The same build run through this session's `!` (no TTY) asked nothing, which is S1.5's designed behaviour.
- The first container probe failed with `Authentication required`: the container's credentials copy carried `expiresAt` 0 and was refused, while the host's `~/.claude/.credentials.json` had expired at 04:57Z and this session's stack home held a newer regular-file copy. That is a harnessed credential defect outside GH-600, reported to the engineer. The engineer logged in inside the container by hand before the passing rerun.
- The pass-2 gauntlet rerun was stopped at the engineer's direction: no source changed after 1f5572c, so the final run's numbers stand.
- Live replies, verbatim. Step-0 probe A (0.89.1, before the change): `NOT LOADED`. Step-0 probe B (a random marker in `rules/harnessed-imports/probe.md`): `GH600-03f20cca27c7`, the exact marker, and the control line from `~/.claude/CLAUDE.md`. S2.3: `Inactive ref/commit views are immutable committed structural/source snapshots: no working-copy LSP, \`search.text\`, or edits.` S3.2: `- **Profiles:** active \`localization\`. …`. The instrument is the agent's report of its own context, not a loader trace; a sentence that exists in one file only is what makes a guess implausible.
- The host adapter was 0.85.1 while the catalog pins 0.89.1. The engineer approved `mise use -g npm:@agentclientprotocol/claude-agent-acp@0.89.1`. This session's PATH still found 0.85.1, so the live runs put the 0.89.1 directory first. `harnessed build`'s adapter offer proposes `npm i -g`, which a mise-shimmed adapter may shadow; out of scope here and reported to the engineer.
- The gortex profile was switched to `localization` for one probe and back to `core`; `active.md` was compared byte-for-byte with `core.md` afterwards. The `hostspike` answer file, copies and owned dir created for the live runs were removed.
- The first baseline ran in the working tree while new files were being written, and its coverage layer failed on the new module's absence from the ledger. It was discarded and rerun in a detached worktree of 267ff1d (green). That failure is also how the ledger entry was found (decisions Revision 3).
- One new test (`test_s1_5_host_exec_never_reaches_the_question`) first passed vacuously because CliRunner swaps `sys.stdin`; it was rewritten to stand in for a terminal and then seen failing before the fix.
- Mutant 1 (`"@" in s` for `s.startswith("@")`) survived until two whitespace-free inputs (`a@b.com`, `` `@foo` ``) were added to S1.4.
