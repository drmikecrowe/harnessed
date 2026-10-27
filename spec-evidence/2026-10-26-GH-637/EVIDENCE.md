## Evidence Report — keep the host Claude login refreshed when the refresher starts from an isolated tree (Tier 3)

## Summary
The Claude login refresher now refreshes the real host login in `~/.claude` even when a launch from an isolated test tree starts it. Two changes do this. `_is_harnessed_owned` now also recognizes a stack home by its `.harnessed-stack` stamp or its sibling `<name>.lock`, not only by its place under the current data root. The refresher's lock and log now live under the data root the refresher syncs, so a refresher for an isolated tree cannot block the real one. Before this change, such a refresher took a stack home for the user's store, let the real login expire, and held the only lock.

Each criterion and its proof:
- A `CLAUDE_CONFIG_DIR` that points at a stack home outside the data root is ignored, by stamp (S1.1) or by sibling lock (S1.2), and the refresh runs against `~/.claude` (S1.5). Each test failed before the fix and passes after it. A hypothesis property test, which also failed first, pins "owned exactly when a marker or containment holds".
- A user's own `CLAUDE_CONFIG_DIR` with no marker is still honored, whether it exists (S1.3) or not (S1.4). Both passed before the fix and were proven by a throwaway mutant.
- The lock and log are keyed to the data root (S2.1, S2.2, S2.3), and only one refresher runs per data root (S2.4).
- The refresher always starts in this case (S2.5).
- One pass turns every stack file into a view with no refresh token (S3.1, S3.2).
- Mutation testing killed every mutant of the three changed functions. A real run against the 2026-10-25 layout resolved the store to `~/.claude`.

Not proven: no layer failed or was skipped. The adversary's single round did not reach most of its hunts (Review risks), and the stamp records a dirty tree because of one untracked story file (Review risks).

## Agent decisions
<details><summary>3 agent decisions</summary>

### A1. The refresher log moves with the lock
- Other option: leave `claude-auth-refresher.log` under `XDG_STATE_HOME` and move only the lock.
- Why: each refresher truncates its log on start, so an isolated refresher would wipe the real one's log, and `_warn_if_refresh_failing` would report the wrong refresher.
- Command: hotfix

### A2. Tier 3, with property and mutation layers
- Other option: Tier 2, the full loop with no property or mutation testing.
- Why: the loop's tier list names auth as Tier 3, and a wrong ownership answer either logs every stack out or writes a login into the wrong file.
- Command: hotfix

### A3. Accept two refreshers for one host store during an upgrade
- Other option: have the new refresher also take the old `XDG_STATE_HOME` lock, so an old-release refresher still blocks it.
- Why: taking the old lock would bring back the starvation this change fixes, and claude's own refresh lock already serializes two refreshes of `~/.claude`.
- Command: hotfix

</details>

### Review risks
- The adversary used 4 of its 10 calls and did not reach most of its hunts (see Not reached by review). Its three hunches were triaged against the code. (1) Lock directory not created: already correct, because `start_refresher` runs `lock.parent.mkdir(parents=True, exist_ok=True)` before it opens the lock or the log, and S2.2, S2.3 and S2.5 pass on a data root with no `harnessed/` directory. (2) S3.1 may be vacuous: already correct, because the test writes the stack file itself (an `old` login 1 hour ahead, the host 8 hours ahead), and the throwaway mutant `_REFRESH_KEYS = ()` failed it. (3) The broader rule also reaches `_host_omp_source`: true. A user's own omp config dir with a sibling `<dir>.lock` now reads as a stack home, and its override is ignored. That is the same trade as the first Known limit in SPEC.md, which names only the Claude config dir. No test covers the omp caller with a marker.
- The final stamp records `dirty: true` at commit `9eae0ba`. All source and test changes were committed in `9eae0ba` before the run. The one uncommitted file when the run started was `spec-evidence/2026-10-26-GH-637/baseline-stamp.json`, an untracked story artifact that no layer reads as input.
- Mutation and property testing are not layers in `tools/gauntlet-layers.json`, and the stamp does not record them. They ran by hand at commit `9eae0ba`'s source (see Gauntlet).

### Not reached by review
- Round 1: calls 4/10; hunts not reached: 1 (merge-gate argument comparison: manifest and workflows not opened), 2 (full caller list of _lock_path, _log_path and _is_harnessed_owned), 4, 5, 6, 8, 9; sites not opened: src/harnessed/claudeauth.py:259 (start_refresher, mkdir and lock-open path), src/harnessed/hosthome.py:_host_omp_source, tools/gauntlet-layers.json, /home/mcrowe/Programming/Personal/harnessed/GH-637-token-refresh/.github/workflows/test.yml, /home/mcrowe/Programming/Personal/harnessed/GH-637-token-refresh/.github/workflows/lint.yml, tests/conftest.py (env fixture)

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: the refresher recognizes a stack home by its markers and keys its lock and log to the data root it syncs, so an isolated launch can no longer leave `~/.claude` unrefreshed.
- Proven: 12/12 scenarios mapped and passing
- Not proven: nothing. The limits are the adversary's partial coverage and the dirty stamp, both under Review risks.

- Process: spec-evidence 0.16.2 (gate files: story-gate.md none, spec-gate.md spec-evidence 0.16.2)
- Spec: spec-evidence/2026-10-26-GH-637/SPEC.md (committed)
- Spec approval: obtained from mcrowe (commit 839a4e9, `GH-637: spec approved`)
- Intent review: not run, engineering lane
- Source state: commit 9eae0baa9a962ca6570a5b5e8849d80dc9db9d18, the commit the final run and the review read
- Baseline: spec-evidence/2026-10-26-GH-637/baseline-stamp.json at commit 839a4e9102e50d0a1a9a0b66ba89450f83d70b22, green

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
    "tests": 342.369,
    "coverage": 508.05,
    "types": 18.199,
    "lint": 0.18,
    "shellcheck": 2.246,
    "secrets": 3.382
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
  "commit": "9eae0baa9a962ca6570a5b5e8849d80dc9db9d18",
  "dirty": true,
  "written": "2026-10-27T12:29:56.192Z"
}
```

</details>

### Spec → Test mapping
Every row is `pass`. "Seen failing" says whether the test failed before the fix (RED), or passed before it and was then proven by a throwaway mutant that made it fail.

<details>
<summary>12/12 scenarios mapped and passing</summary>

| Scenario | Test | Seen failing | Status |
|---|---|---|---|
| S1.1 | `tests/test_claudeauth.py::TestStackHomeMarkers::test_a_stamped_stack_home_outside_the_data_root_is_not_the_store` | RED before the fix | pass |
| S1.2 | `tests/test_claudeauth.py::TestStackHomeMarkers::test_an_unstamped_home_with_its_sibling_lock_is_not_the_store` | RED before the fix | pass |
| S1.3 | `tests/test_claudeauth.py::TestStackHomeMarkers::test_a_user_dir_with_no_marker_is_honored` | pre-existing behavior; mutant `_is_harnessed_owned` returns True: killed | pass |
| S1.4 | `tests/test_claudeauth.py::TestStackHomeMarkers::test_a_missing_user_dir_is_honored` | pre-existing behavior; same mutant: killed | pass |
| S1.5 | `tests/test_claudeauth.py::TestStackHomeMarkers::test_the_refresh_runs_against_the_host_store` | RED before the fix | pass |
| S2.1 | `tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_the_lock_and_log_live_under_the_data_root` | RED before the fix | pass |
| S2.2 | `tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_another_data_roots_refresher_does_not_block_this_one` | RED before the fix | pass |
| S2.3 | `tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_another_data_roots_lock_is_left_free` | pre-existing behavior; mutant lock keyed to the config dir's data root with the fd left open: killed | pass |
| S2.4 | `tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_one_refresher_per_data_root` | pre-existing behavior; mutant that ignores a held lock: killed | pass |
| S2.5 | `tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_a_stack_config_dir_never_stops_the_start` | RED before the fix | pass |
| S3.1 | `tests/test_claudeauth.py::TestOnePassConvertsStackFiles::test_a_stack_file_becomes_a_view` | pre-existing behavior; mutant `_REFRESH_KEYS = ()`: killed | pass |
| S3.2 | `tests/test_claudeauth.py::TestOnePassConvertsStackFiles::test_an_isolated_pass_keeps_the_refresh_token_in_the_host_store` | pre-existing behavior; same mutant: killed | pass |

</details>

The property in the Verification contract is `tests/test_claudeauth.py::test_owned_exactly_when_a_marker_or_containment_holds`. It was RED before the fix and passes now.

The Must NOT items: the four `TestHostClaudeSource` override tests and `test_the_child_inherits_the_held_lock` pass unchanged in the tests layer. `git diff 839a4e9..9eae0ba -- tests/` adds lines to `tests/test_claudeauth.py` only and edits no existing test. No signature of `host_store`, `start_refresher`, `sync`, `tick`, `refresh_host` or `_is_harnessed_owned` changed. `pod_view_path`, `_pod_views` and `_views_lock` still use `_state_root()`.

### Gauntlet (final fresh run)
All rows PASSED.

<details>
<summary>6/6 manifest layers PASSED, plus 4 layers run by hand, all PASSED</summary>

| Layer | Command | Status + result | Baseline | Selection | Log |
|---|---|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4619 passed, 79 skipped; baseline 4606 passed, 79 skipped; +13 new tests | reused | off | `work/tests.log` |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 86.38% total, threshold 80%; 4619 passed | reused | off | `work/coverage.log` |
| types | `mise exec -- sh -c 'pyright --pythonpath ...'` | PASSED — 0 errors, 0 warnings, 0 informations | reused | off | `work/types.log` |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — All checks passed | reused | off | `work/lint.log` |
| shellcheck | `mise exec -- sh -c 'shellcheck $(git ls-files "*.sh")'` | PASSED — no findings | reused | off | `work/shellcheck.log` |
| secrets | `mise exec -- gitleaks detect --no-banner --redact` | PASSED — 1508 commits scanned, no leaks found | reused | off | `work/secrets.log` |
| mutation (by hand) | `HARNESSED_DIR=$PWD mise exec -- uv run --extra dev mutmut run "harnessed.hosthome.x__is_harnessed_owned*" "harnessed.claudeauth.x__lock_path*" "harnessed.claudeauth.x__log_path*"`, with `tests_dir` scoped to `tests/test_claudeauth.py` and `tests/test_launch_host.py` for the run (pyproject.toml restored after) | PASSED — 14/14 killed: `_is_harnessed_owned` 8/8, `_lock_path` 3/3, `_log_path` 3/3 | none | not in stamp | `/tmp/gh637-mutmut-results.log` |
| property (by hand, also in the tests layer) | `tests/test_claudeauth.py::test_owned_exactly_when_a_marker_or_containment_holds` (hypothesis over stamp, lock, containment, existence) | PASSED — RED before the fix, green after | none | not in stamp | `work/tests.log` |
| real execution (by hand) | the branch venv's python, `CLAUDE_CONFIG_DIR=~/.local/share/harnessed/home/gortex-ghissues/claude` (the real stack home, with stamp and sibling lock), `XDG_DATA_HOME=<tmp>/iso`, calling `host_store()`, `_lock_path()` and `_log_path()`, read-only | PASSED — store `/home/mcrowe/.claude/.credentials.json`; lock and log under `<tmp>/iso/harnessed/` | none | not in stamp | session output |
| adversary | `spec-evidence-adversary`, fresh, 1 round, range `da6c524...9eae0ba` | PASSED — 0 findings, 3 hunches triaged (Review risks) | none | not in stamp | `spec-evidence/2026-10-26-GH-637/findings-code.md` |

</details>

### Layers not run as specified
- N-A: none
- UNAVAILABLE: none
- SUBSTITUTED: none. The mutation run narrowed `tests_dir` to the two files that cover the changed functions, as the `[tool.mutmut]` comment in `pyproject.toml` prescribes. The full `tests/` dir fails mutmut's stats run on `HomeNotFoundError` and on symlink-asserting tests.
- Merge gate parity: `test.yml` maps to tests and coverage, and `lint.yml` maps to lint, types and shellcheck. `live.yml` does not trigger, because no file in its trigger list changed. `pr-title.yml` is checked when the PR opens.

### Defect classes closed
- Generator: code that decides "is this a harnessed stack home" by containment under the CURRENT `host_homes_root()`, or that keys per-machine refresher state to a root other than the data root it syncs.
- Enumerated by: every caller of `_is_harnessed_owned` (SPEC.md fact 8, Gortex `relations usages`), plus `rg -n 'host_homes_root\(\)\.resolve|_state_root\(\)' src/harnessed`.
- Sites: 7. `hosthome.py` `_is_harnessed_owned`: fixed. Its callers `_host_claude_config_override` and `_host_omp_source`: fixed through it. `claudeauth.py` `_lock_path` and `_log_path`: fixed. `claudeauth.py` `pod_view_path`, `_views_lock` and `_pod_views`: not applicable, because pods bind-mount those paths under `XDG_STATE_HOME` (SPEC.md Must NOT).

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | unrecorded | unrecorded |
| spec-evidence-intent | — | not run, engineering lane | — |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 195589/2066 |

### Process notes
- The first `mutmut run` failed its stats collection with `HomeNotFoundError`, because the `mutants/` tree has no `src/harnessed/catalog` symlink. The rerun used the two fixes the `[tool.mutmut]` comment documents: `HARNESSED_DIR=$PWD`, and a scoped `tests_dir`.
- The first real-execution attempt set `XDG_DATA_HOME` on `mise exec`, which moved mise's own data dir. mise then tried to install its tool set into the temp dir and failed before python ran. The temp dir was removed. The rerun called the branch venv's python directly.
- S3.1 first compared against `claudeauth._REFRESH_KEYS`, so a mutant of that constant would pass it vacuously. Before the mutant run, the test was changed to name the two keys literally. The test was new and its intent did not change.
- The adversary transcript also names `claude-opus-5-5` once, on a request-shape metadata line. Every assistant turn names `claude-sonnet-5-5`.
