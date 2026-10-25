## Evidence Report — Host launches stop wiping a profile another launch or session uses (Tier 2)

## Summary
Delivered: a host launch (`host-run`, `host-acp`) now claims the stack's profile before it assembles. Before this change, every launch reset the profile with an unlocked rmtree. Concurrent ACP starts then crashed with `ENOENT`, and a later launch deleted the files a live session read. `_claim_profile` in `src/harnessed/hosthome.py` takes a build gate and a session lock beside the profile directory. `_launch_host` assembles and merges settings only when its claim builds. Otherwise it reuses the profile and prints one in-use line.

Each criterion and its proof:
1. Two launches at the same time both succeed and build once: S1.1 and S1.2, real subprocesses racing on real `flock`.
2. A launch during a live session reuses the profile, prints the in-use line, and skips the settings merge (A1): S2.1 and S2.2, an in-process `host-run` with a subprocess holding the session lock.
3. After every session ends, a SIGKILLed one included, the next launch builds: S3.1. The first claim on a clean tree builds and creates both lock files: S3.2.
4. A failed build releases the locks: S4.1 in-process (assemble raises `SchemaError`), S4.2 with a builder process that dies before `done()`.
5. The session lock survives `exec` and the gate does not: S5.1, S5.2, S5.3.
6. `host-run` and `host-acp` each claim once, and `project-setup` never claims: S6.1, S6.2.
7. The lock files survive `reset_profile`: S7.1.

All 15 scenarios pass, and all 6 gauntlet layers passed on commit `61184e7`. Not proven: the `live` and `live-docker` CI jobs, which run only on the PR.

## Agent decisions
<details><summary>1 agent decision</summary>

### A1. A reused profile does not get the host settings merge
- Other option: run `_merge_host_claude_settings` on every launch, as today, including when the profile is reused.
- Why: the merge rewrites `settings.json` inside a profile a live session uses, which is the class of write this change stops; the builder already merged it, and host settings changes then apply after every session closes, like stack changes.
- Command: hotfix

</details>

### Review risks
- Adversary hunch 1: on the busy path, a held session lock is the only evidence that the profile exists. If `harnessed build` or `harnessed clean` deleted the profile under a live session (SPEC Known limits), the next launch skips `assemble` and fails later in materialization, not with a clear error. No scenario covers this.
- Adversary hunch 2: after `done()`, only the local `claim` in `_launch_host` keeps the shared lock alive until the exec, the relay, or the `--rm` run. A refactor that drops the binding drops the lock silently. S5 proves the exec path in isolation. No test holds the lock across `_relay_acp` or `subprocess.run`. I read `acprelay.run`: it runs the agent as a `Popen` child, and `_launch_host`'s frame stays alive until `os._exit`, so the current code holds the lock.
- The adversary's range starts at `cd0235c` (the merge base with `origin/HEAD`). It includes `a9229b5` `fix(install)`, which this branch inherited from the unmerged `origin/fix-mise-install`. That commit is not part of this SPEC, and the PR will carry it unless the branch is rebased onto main.
- Most of the `launcher.py` hunk is a 4-space re-indent of the claim-to-merge span. Its whitespace-blind diff is 23 insertions and 9 deletions.

### Not reached by review
- Round 1: calls 5/10; hunts not reached: 2 (callers of _launch_host and assemble were not enumerated: the Grep was blocked by the Gortex hook and I did not retry), 6, 7, 9 (acprelay.run was not read to check whether it passes fds to the agent child, or whether the relay path actually holds the claim); sites not opened: /home/mcrowe/Programming/Personal/harnessed/GH-631-acp-live-sessions/src/harnessed/launcher.py (post-done() region: _host_home_lock, exec, subprocess.run and _relay_acp paths), /home/mcrowe/Programming/Personal/harnessed/GH-631-acp-live-sessions/src/harnessed/acprelay.py, /home/mcrowe/Programming/Personal/harnessed/GH-631-acp-live-sessions/src/harnessed/emit.py:47, other callers of assemble, such as _build_stack and the container launch

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: `_launch_host` claims the profile with a build gate and an inherited session lock, and assembles only when no session or build holds it.
- Proven: 15/15 scenarios mapped and passing
- Not proven: the `live` and `live-docker` layer (runs on the PR only)

- Process: spec-evidence 0.16.2
- Spec: spec-evidence/2026-10-25-GH-631/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit `c5a3ab4`, `GH-631: spec approved`)
- Intent review: not run, engineering lane
- Source state: commit 61184e770fc62b50d8ff348e9d3eaff50cf4828b — the commit the final run and the review read. The stamp says `dirty: true`. The only change was the untracked `spec-evidence/2026-10-25-GH-631/baseline-stamp.json`, which this commit adds. No source file was dirty.
- Baseline: baseline-stamp.json at commit c5a3ab4a5ee9f8139ea1a1e68ebb43b67fa05348, green

<details>
<summary>Stamp: green, 6/6 layers</summary>

```json
{
  "result": "green",
  "mode": "full",
  "expected_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "completed_layers": ["tests", "coverage", "types", "lint", "shellcheck", "secrets"],
  "layer_seconds": {"tests": 341.469, "coverage": 440.736, "types": 16.541, "lint": 0.125, "shellcheck": 1.787, "secrets": 2.735},
  "layers": {
    "tests": {"baseline": "reused", "selection": "off"},
    "coverage": {"baseline": "reused", "selection": "off"},
    "types": {"baseline": "reused", "selection": "off"},
    "lint": {"baseline": "reused", "selection": "off"},
    "shellcheck": {"baseline": "reused", "selection": "off"},
    "secrets": {"baseline": "reused", "selection": "off"}
  },
  "failed": null,
  "exit_code": 0,
  "commit": "61184e770fc62b50d8ff348e9d3eaff50cf4828b",
  "dirty": true,
  "written": "2026-10-25T12:07:23.825Z"
}
```

</details>

### Spec → Test mapping
<details>
<summary>15/15 scenarios mapped and passing</summary>

| Scenario | Test | Status |
|---|---|---|
| S1.1 | tests/test_profile_claim.py::TestConcurrentLaunchesBuildOnce::test_s1_1_two_racing_claims_both_succeed_and_build_once | pass |
| S1.2 | tests/test_profile_claim.py::TestConcurrentLaunchesBuildOnce::test_s1_2_the_second_claim_prints_the_in_use_line_once | pass |
| S2.1 | tests/test_host_acp.py::TestTheProfileClaim::test_s2_1_a_live_sessions_profile_is_reused_not_reset | pass |
| S2.2 | tests/test_host_acp.py::TestTheProfileClaim::test_s2_2_a_reused_profile_gets_no_settings_merge | pass |
| S3.1 | tests/test_profile_claim.py::TestAfterEverySessionEnds::test_s3_1_a_killed_session_releases_the_profile | pass |
| S3.2 | tests/test_profile_claim.py::TestAfterEverySessionEnds::test_s3_2_a_first_claim_creates_the_dir_and_both_lock_files | pass |
| S4.1 | tests/test_host_acp.py::TestTheProfileClaim::test_s4_1_a_failed_build_releases_the_locks | pass |
| S4.2 | tests/test_profile_claim.py::TestFailedBuildReleases::test_s4_2_a_builder_that_dies_hands_the_build_to_the_waiter | pass |
| S5.1 | tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_1_the_session_lock_is_held_after_exec | pass |
| S5.2 | tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_2_killing_the_execd_process_releases_it | pass |
| S5.3 | tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_3_the_gate_fd_does_not_reach_the_execd_process | pass |
| S6.1 | tests/test_host_acp.py::TestTheProfileClaim::test_s6_1_host_run_and_host_acp_each_claim_once | pass |
| S6.2 | tests/test_host_acp.py::TestTheProfileClaim::test_s6_2_project_setup_never_claims | pass |
| S7.1 | tests/test_profile_claim.py::TestLockFilesOutliveAReset::test_s7_1_reset_profile_leaves_both_lock_files | pass |

RED: before the implementation, S2.1 and S2.2 failed on the defect itself: the second launch called `assemble` and the merge under a live session. The other new tests failed on the missing `_claim_profile`.

Must NOT mapping:
- `assemble`, `emit.reset_profile`, `_build_stack` unchanged: none of them appears in the diff of `61184e7`. `harnessed build` and `container-run` are covered by the full suite (tests layer).
- `_host_home_lock` and the fingerprint gate unchanged: not in the diff. The tests layer covers them.
- The settings merge when the launch builds: same call and same arguments (diff of `launcher.py`, condition only). The first launch in S2.1 records the merge call.
- No counter file or PID file: `_claim_profile` writes no file content (`src/harnessed/hosthome.py`). The counter file in S1.1 belongs to the test.
- The gate fd does not reach the harness: S5.3.
- Test count not lowered: 4666 collected at baseline, 4680 now (14 new). The final run: 4601 passed, 79 skipped.

</details>

### Gauntlet (final fresh run)
`live` and `live-docker` did not run here. They run on the PR because `launcher.py` is a live trigger.

<details>
<summary>6/6 layers PASSED</summary>

| Layer | Command | Status + result | Baseline | Selection | Log |
|---|---|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4601 passed, 79 skipped, 0 failed | reused | off | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 86.38% branch coverage (threshold 80%) | reused | off | work/coverage.log |
| types | pyright over the dev environment | PASSED — 0 errors, 0 warnings | reused | off | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — All checks passed | reused | off | work/lint.log |
| shellcheck | `shellcheck $(git ls-files "*.sh")` | PASSED — 0 findings | reused | off | work/shellcheck.log |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — no leaks found | reused | off | work/secrets.log |

</details>

### Layers not run as specified
- N-A: none
- UNAVAILABLE: none
- SUBSTITUTED: none
- Not run here: `live` / `live-docker` (SPEC verification contract). They run in CI on the PR, and the PR must show both green.
- No mutation testing, property-based tests or changed-line coverage layer exists in `tools/gauntlet-layers.json`, and the Tier 2 contract does not require them.

### Defect classes closed
- Generator: a host launch path that resets or rewrites the assembled profile without holding the profile claim.
- Enumerated by: `rg -n '\bassemble\(|\breset_profile\b|_merge_host_claude_settings\(' src/harnessed/launcher.py`. It returns 8 lines: 4 are comments, and 4 are call sites.
- Sites: 4 — `launcher.py:3193` `_launch_host` assemble: fixed (claim-gated). `launcher.py:3352` `_launch_host` settings merge: fixed (claim-gated, A1). `launcher.py:825` `_build_stack` assemble (`harnessed build`): not applicable, SPEC Known limits. `launcher.py:4760` `container_run` merge: not applicable, container path, SPEC Must NOT.

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 102609/1645 |
| spec-evidence-intent | — | not run, engineering lane | unrecorded |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 328099/5397 |

### Process notes
- S5.1 failed on its first green run: the test child dropped the claim object right after `done()`, so CPython closed the fd before the exec. I fixed the test only, by binding the claim the way `_launch_host` does, and it passes. The implementation did not change.
- The first baseline run used the wrong `--store` path (`spec-evidence/work/baselines`). I stopped it after a few seconds, deleted the directory, and reran it against `work/baselines`.
- Adversary round 1 returned 0 findings, so no fix changed code and no round 2 ran.
- The Gortex index served `main/` during part of the session, and its worktree route was rebuilding. I read worktree files by absolute path.
