## Evidence Report — Merge ~/.claude.json so trust, import and in-stack answers persist (Tier 2)

## Summary
**What was delivered, and why.** A stack's `.claude.json` is no longer thrown away on every launch. One pure function, `merge_claude_json`, keeps the stack's live file and lays only harnessed's own keys over it: the onboarding flag, the start counters, the identity pair, and folder trust and import approval for the launch's project. The container stub and the host home both use it. A host rebuild keeps the file, the host path drops a legacy copy's `mcpServers`, and under `host-acp`, `project-setup` seeds trust for each new session folder. Before this, both paths overwrote the file, so no answer persisted.

**Each criterion and how it was proven.**
- AC-1, no trust or import question on the first launch: unit tests on both paths, plus a live run of each path twice in a new folder by the engineer, with no question shown. The API key question appeared on each path's first launch, which the criterion allows.
- AC-2, the API key answer persists and a "no" stays a "no": unit tests on both paths keep `customApiKeyResponses`, including a `rejected` entry, unchanged across a relaunch. Live, with a dummy API key: answered once per path, then not asked again, including after the container was removed and relaunched.
- AC-3, other in-stack answers survive and harnessed's onboarding flag still wins: unit tests on both paths, and the live container stub kept Claude's own session keys beside the seeded ones.
- AC-4, no host identity under `isolated_auth`: unit tests on the merge, the container stub and the host backend, including a stack switched to isolated after a shared launch.
- AC-5, no host `mcpServers` in the stack file, while the stack's own servers still load: unit tests, including a legacy copy left by an older launch.
- AC-6 (an ACP session loads the external import) was removed from the story and moved to #600 (Revision 5). The `host-acp` folder-trust seeding it relied on is built and proven (S3.9); the import itself cannot load, because a headless ACP session expands no `@`-imports.

**Not proven.** No story criterion. The adversary review is not clean: in both rounds, a hook blocked its source reads, so its caller and gate hunts did not run, and the last commit (`7f638b2`, the smoke script) came after round 2.

**Judgment calls.** Five, all ruled by the engineer or recorded as revisions. The host path honours `isolated_auth` (Decide 1). `host-acp` seeds each new session folder (Decide 2, against its default). The host path always drops top-level `mcpServers` (Revision 3, from adversary round 1). The smoke script now prints the agent's reply (Revision 4). AC-6 and S4.2 left this story for #600 after the evidence gates (Revision 5), once marker tests showed what does reach an ACP session. A real regression was also caught and fixed during mutation testing: reading `isolated_auth` at `HostBackend` construction broke a capability-warning test. The flag is now read inside the home lock.

## Orientation
- Verdict: PASSED WITH LIMITS (the substituted layers below)
- Delivered: both launch paths merge `.claude.json` over its live copy, seed trust and import approval for the project, and keep host identity and host MCP servers out.
- Proven: 27 of 27 scenarios pass (S4.2 removed by Revision 5).
- Not proven: live layer UNAVAILABLE until the PR, adversarial review SUBSTITUTED (both rounds blocked from source reads; `7f638b2` after round 2), mutation SUBSTITUTED (narrowed tests; 8 equivalent survivors named).

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-12-GH-594/SPEC.md (committed)
- Spec approval: obtained from mcrowe, commit `fdea3f8`
- Intent review: S1.7 names the empty-placeholder choice; S3.2 carries a `rejected` entry; S3.5 states that AC-2 and AC-3 need it; S3.8 added for AC-5's negative; S4.1 runs `host-run` as well and expects the API key question on the first launch only; Known limits name the `host-acp` limit. One gap declined (host identity wins when shared), see `decisions.md`.
- Source state: commit `b738c362e44727f9b2fb5d1d10ffc7c061135f18` — the commit the final run read. Its last code commit is `7f638b2`; the commits after it touch only the story directory. The adversary's last round read `14c93f5`.
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
    "tests": 239.162,
    "coverage": 349.902,
    "types": 18.992,
    "lint": 0.187,
    "shellcheck": 1.82,
    "secrets": 3.181
  },
  "failed": null,
  "exit_code": 0,
  "commit": "b738c362e44727f9b2fb5d1d10ffc7c061135f18",
  "dirty": false,
  "written": "2026-10-13T16:09:40.454Z"
}
```
- Baseline: baseline-stamp.json at commit `fdea3f8d80fc36c99c2b34ada4ae05e716a618ac`, green; 4329 tests collected.

### Spec → Test mapping
Test ids are relative to `tests/`. `TestHostClaudeJsonMerge` is in `test_launch_host.py`; `TestStubMergesOverTheLiveFile` is in `test_claude_config_seed.py`.

| Scenario | Test | Status |
|---|---|---|
| S1.1 | `test_claude_json_merge.py::test_s1_1_empty_inputs_give_exactly_the_owned_shape` | pass |
| S1.2 | `test_claude_json_merge.py::test_s1_2_live_answers_survive_and_the_project_gains_its_keys` | pass |
| S1.3 | `test_claude_json_merge.py::test_s1_3_onboarding_is_forced_true` | pass |
| S1.4 | `test_claude_json_merge.py::test_s1_4_start_counters_keep_live_values` | pass |
| S1.5 | `test_claude_json_merge.py::test_s1_5_host_contributes_nothing_but_identity` | pass |
| S1.6 | `test_claude_json_merge.py::test_s1_6_shared_identity_comes_from_the_host` | pass |
| S1.7 | `test_claude_json_merge.py::test_s1_7_isolated_with_no_live_identity_gets_empty_placeholders` | pass |
| S1.8 | `test_claude_json_merge.py::test_s1_8_isolated_keeps_the_clients_own_login` | pass |
| S1.9 | `test_claude_json_merge.py::test_s1_9_isolated_scrubs_host_identity_left_by_a_shared_launch` | pass |
| S1.10 | `test_claude_json_merge.py::test_s1_10_no_project_leaves_projects_alone` | pass |
| S1.11 | `test_claude_json_merge.py::test_s1_11_non_dict_inputs_count_as_empty` | pass |
| S1.12 | `test_claude_json_merge.py::test_s1_12_property_live_keys_survive_and_host_adds_only_identity` (hypothesis, 200 examples) | pass |
| S2.1 | `TestStubMergesOverTheLiveFile::test_s2_1_first_launch_seeds_trust_for_the_project` | pass |
| S2.2 | `TestStubMergesOverTheLiveFile::test_s2_2_answers_in_the_stub_survive_a_relaunch` | pass |
| S2.3 | `TestStubMergesOverTheLiveFile::test_s2_3_an_unreadable_stub_is_rebuilt` | pass |
| S2.4 | `TestStubMergesOverTheLiveFile::test_s2_4_the_container_backend_passes_the_project` | pass |
| S3.1 | `TestHostClaudeJsonMerge::test_s3_1_first_launch_takes_identity_and_trust_but_not_host_state` | pass |
| S3.2 | `TestHostClaudeJsonMerge::test_s3_2_in_stack_answers_survive_a_relaunch` | pass |
| S3.3 | `test_launch_host.py::TestHostClaudeSource::test_launching_a_stack_from_inside_itself_does_not_copy_its_account_over_itself`, `::TestHostClaudeSource::test_a_nested_launch_snapshots_the_users_account_not_the_parent_stacks`, `::TestShareClaudeState::test_claude_json_seeded_from_home_level_not_config_dir` | pass |
| S3.4 | `TestHostClaudeJsonMerge::test_s3_4_isolated_auth_keeps_host_identity_out`, `::test_s3_4_host_backend_carries_isolated_auth_into_the_seed`, `::test_s3_4_launch_host_builds_the_backend_from_the_stack` (structural) | pass |
| S3.5 | `TestHostClaudeJsonMerge::test_s3_5_a_rebuild_keeps_the_claude_json` | pass |
| S3.6 | `TestHostClaudeJsonMerge::test_s3_6_host_acp_seeds_no_project_for_the_launch_folder` | pass |
| S3.7 | `TestHostClaudeJsonMerge::test_s3_7_no_user_file_still_seeds_onboarding_and_trust` | pass |
| S3.8 | `TestHostClaudeJsonMerge::test_s3_8_the_stacks_servers_load_and_the_users_do_not` | pass |
| S3.9 | `TestHostClaudeJsonMerge::test_s3_9_project_setup_seeds_only_the_session_folder`, `::test_s3_9_project_setup_writes_no_file_that_is_not_there`, `::test_s3_9_project_setup_calls_the_seed_and_nothing_else_in_the_home` (structural); live: `decisions.md` Revision 4, runs 1 to 3, keys read back | pass |
| S3.10 | `TestHostClaudeJsonMerge::test_s3_10_a_legacy_copy_loses_the_users_mcp_servers` | pass |
| S4.1 (trust and import) | manual, engineer, 2026-10-12: `container-run` and `host-run` twice each in `/home/mcrowe/scratch-gh-594-v4`, stack `hostspike`; no question on any launch. The container stub held Claude's own `lastSessionId` and the seeded keys under the same project key. | pass |
| S4.1 (API key) | manual, engineer, 2026-10-13, in `/home/mcrowe/scratch-gh-594-apikey`, with a dummy `ANTHROPIC_API_KEY` (`sk-ant-dummy-gh594-` plus 20 zeros: in the project `.env` for the container path, exported for the host path). Run 1: asked on each path's first launch, answered Yes, not asked on the second. The second container launch then was an attach, so run 2 put `harnessed rm hostspike` before each `container-run`: 4 launches, no question on any. Read-back: the container stub `~/.local/state/harnessed/harnessed-claude-hostspike-02deba0b/claude.json` and the host file `~/.local/share/harnessed/home/hostspike/claude/.claude.json` both hold `customApiKeyResponses.approved = ["00000000000000000000"]` and the trust keys after the relaunch | pass |

Story criteria, by clause:

| Criterion clause | Test | Status |
|---|---|---|
| AC-1 condition: no trust or import question on the first launch | `test_s2_1_first_launch_seeds_trust_for_the_project`, `test_s3_1_first_launch_takes_identity_and_trust_but_not_host_state`, `test_s3_7_no_user_file_still_seeds_onboarding_and_trust`; S4.1 manual | pass |
| AC-1 boundary: both paths | S2.1 (container) and S3.1 (host) tests above; S4.1 ran both | pass |
| AC-1 negative: the API key question may stay, since harnessed writes no key fragment | `test_s1_1_empty_inputs_give_exactly_the_owned_shape` (no `customApiKeyResponses` in the exact shape), `test_s1_5_host_contributes_nothing_but_identity` | pass |
| AC-2 condition: once answered, the API key question does not return | `test_s1_2_live_answers_survive_and_the_project_gains_its_keys`, `test_s2_2_answers_in_the_stub_survive_a_relaunch`, `test_s3_2_in_stack_answers_survive_a_relaunch`; S4.1 (API key) manual, both paths, across a real container relaunch | pass |
| AC-2 boundary: both paths, same stack and project | S2.2 and S3.2 tests above | pass |
| AC-2 negative: a declined key stays declined | S1.2, S2.2 and S3.2 tests keep `rejected: ["def"]` unchanged | pass |
| AC-3 condition: an in-stack answer survives a relaunch | `test_s2_2_answers_in_the_stub_survive_a_relaunch`, `test_s3_2_in_stack_answers_survive_a_relaunch` | pass |
| AC-3 boundary: both paths | S2.2 and S3.2 tests above; S4.1 container stub kept Claude's session keys | pass |
| AC-3 negative: `hasCompletedOnboarding` is reset to harnessed's value | `test_s1_3_onboarding_is_forced_true` | pass |
| AC-4 condition: no host identity under `isolated_auth` | `test_s1_7_isolated_with_no_live_identity_gets_empty_placeholders`, `test_s1_9_isolated_scrubs_host_identity_left_by_a_shared_launch`, `test_s3_4_isolated_auth_keeps_host_identity_out` | pass |
| AC-4 boundary: both paths | container: `test_claude_container_auth.py::TestIsolatedAuthDoesNotLeakHostAccountMetadata::test_isolated_seed_omits_account_identity`; host: `test_s3_4_host_backend_carries_isolated_auth_into_the_seed` | pass |
| AC-4 negative: without isolation the host path copies identity | `test_s1_6_shared_identity_comes_from_the_host`, `test_s3_1_first_launch_takes_identity_and_trust_but_not_host_state` | pass |
| AC-5 condition: host `mcpServers` absent from the stack file | `test_s1_5_host_contributes_nothing_but_identity`, `test_s3_1_first_launch_takes_identity_and_trust_but_not_host_state`, `test_s3_10_a_legacy_copy_loses_the_users_mcp_servers` | pass |
| AC-5 boundary: the host path | S3.1 and S3.10 tests above | pass |
| AC-5 negative: the stack's own servers still load | `test_s3_8_the_stacks_servers_load_and_the_users_do_not` | pass |

### Gauntlet (final fresh run)
| Layer | Command | Status + result | Log |
|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4361 collected (baseline 4329, +32), 0 failures, 239.2 s | gauntlet stdout, scratchpad `gauntlet-pass2.log` |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 86% total, branch on, threshold 80 | `.coverage` from this run |
| types | pyright (manifest command) | PASSED — 0 errors | `gauntlet-pass2.log` |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — 0 findings | `gauntlet-pass2.log` |
| shellcheck | `mise exec -- sh -c 'shellcheck $(git ls-files "*.sh")'` | PASSED — 0 findings | `gauntlet-pass2.log` |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — 0 leaks | `gauntlet-pass2.log` |
| property | inside tests: S1.12 | PASSED — 200 examples | tests layer |
| mutation | `HARNESSED_DIR=$PWD mise exec -- uv run --extra dev mutmut run` on `jsonmerge.x_merge_claude_json*`, `x_seed_claude_project*`, `x_read_json_or_empty*`, `hosthome.x__seed_host_claude_json*`, `x__seed_host_claude_project*`, `x__write_json_atomic*`; `tests_dir` narrowed | SUBSTITUTED — run 1 (`dd4bcde` code): 131 mutants, 118 killed, 13 survived. Re-run of `_seed_host_claude_json` at `e903746` code: 37 of 37 killed (the 5 `now` survivors and the new `mcpServers` drop). 8 survivors remain, all named exclusions: `_write_json_atomic` mutants 4, 6, 13 and `read_json_or_empty` mutants 2, 4 change only the `encoding` argument, equivalent on this UTF-8 host with ASCII fixtures; `_write_json_atomic` mutants 8, 10, 11 change only `indent`, whitespace no reader depends on. `merge_claude_json` and `seed_claude_project`: 0 survivors. | scratchpad `mutmut-results.log`, `mutmut-r2-results.log` |
| live | `live.yml` on the PR (`launcher.py` touched) | not yet run: it runs when the PR opens | — |
| manual | S4.1 | PASSED — trust, import and API key, both paths, including a real container relaunch | `decisions.md` Revision 4, this table's S4.1 rows |
| adversarial review | `spec-evidence-adversary`, 2 rounds | round 1: 1 finding (fixed, `e903746`), 4 hunches (checked, none a defect); round 2: 0 findings, 3 hunches (checked, none a defect) | `findings-code-round1.md`, `findings-code.md` |

### Layers not run as specified
- UNAVAILABLE: live — `live.yml` runs on `pull_request` and no PR exists yet; it gates the merge.
- SUBSTITUTED: adversarial review — both rounds ran, but a Gortex hook blocked the reviewer's Read and Grep on `src/`, so its caller-set and gate-comparison hunts did not run. The author enumerated callers of the changed functions by `rg` instead (`HostBackend.seed_auth`: one production caller, `launcher.py:3363`); that is not independent review. `7f638b2` (the smoke script's reply line) came after round 2 and was not reviewed.
- SUBSTITUTED: mutation — not a declared layer; run by hand with `tests_dir` narrowed to the covering test files, the remedy `pyproject.toml` documents for mutmut's symlink limitation. It cannot see a mutant only a test outside those files would kill.

### Defect classes closed
- Generator: a key that the old wholesale host copy put in the stack file and that the live-file merge now keeps.
  - Enumerated by: the top-level keys of the old copy (`shutil.copy2` of the whole user file), read against `merge_claude_json`.
  - Sites: 4 — `mcpServers`: fixed (`e903746`, S3.10). `oauthAccount`/`userID`: already correct, scrubbed under `isolated_auth` (S1.9) and host-owned otherwise (S1.6). `projects`: not fixed, the leftover entries name the user's own folders on the same machine (Known limits). `customApiKeyResponses`: not fixed, the host's own approvals for its own key on the same machine.
- Generator: a stack field read before `wire_services`, where a test stubs the stack as `None`.
  - Enumerated by: `rg -n 'host_stk\.' src/harnessed/launcher.py`.
  - Sites: 1 — `host_stk.isolated_auth` at `HostBackend` construction: fixed (`687a072`), now read inside the home lock beside `seed_auth`.
- Generator: the seeded `now` value is never asserted.
  - Enumerated by: `rg -n 'now=datetime' src/harnessed`.
  - Sites: 2 — `hosthome._seed_host_claude_json` and `mounts._claude_config_seed_mount`: both fixed by tests (`6026748`) that assert a UTC ISO stamp from this minute, run at UTC+14.

### Not reached by review
- Round 1: calls 5/10; hunts not reached: 1 (gate commands vs layer manifest: the manifest, test.yml and lint.yml were not opened), 2 (callers of the changed functions outside the diff, e.g. other HostBackend constructors or other users of _share_host_claude_state), 6, 7, 8 (no EVIDENCE.md in the diff), 9 (the keep= parameter was not confirmed), 10; sites not opened: /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/hosthome.py:_clear_host_home_except_runtime, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/hosthome.py:_host_fresh_wipe, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/launcher.py:_launch_host (the project_only condition near line 3363), /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/tools/gauntlet-layers.json, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/lint.yml
- Round 2: calls 4/10; hunts not reached: 1 (gate commands against tools/gauntlet-layers.json, test.yml and lint.yml were not opened), 2 (callers outside the diff of _share_host_claude_state, HostBackend( and _claude_config_seed_mount were not enumerated), 3, 5, 6, 7, 8, 9 (the keep= parameter of _clear_host_home_except_runtime was not confirmed), 10; sites not opened: /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/hosthome.py:_clear_host_home_except_runtime, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/launcher.py:_launch_host, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/tools/gauntlet-layers.json, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/lint.yml

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 127847/1225 |
| spec-evidence-intent | 1 | claude-sonnet-5-5 | 61458/236 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 213405/1217 |
| spec-evidence-adversary | 2 | claude-sonnet-5-5 | 230150/1074 |
