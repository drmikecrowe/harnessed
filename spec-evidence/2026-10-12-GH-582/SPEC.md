# SPEC — scheduled pin upgrades every other day

## Summary
**What it achieves.** A GitHub workflow runs `harnessed update` every other day with no person at it. When a pin moved, it opens one signed-commit PR titled `feat(catalog): upgrade pins <date>` and starts the required `pytest` check on it. When nothing moved, it creates no branch and no PR.

**Why.** Today a person runs `mise run upgrade-pr` by hand, and that task never runs `harnessed update`. The weekly `pin-check.yml` only reports. Pins drift between manual runs.

**What changes.** A new script `tools/pin-upgrade.sh` holds the whole run. A new workflow `.github/workflows/pin-upgrade.yml` runs it on a schedule. `harnessed update` gets a `--no-rebuild` flag, so the run never tries the claude and antigravity image rebuild that `--yes` offers. The story says a runner has no podman (#563); with no runtime the rebuild only warns, and if the runner image does carry one, it would build. The flag makes the run the same in both cases. `pin-check.yml` and its test file are deleted. A new workflow test carries pin-check's trigger rules over.

**Each criterion in plain words.**
- AC-1: no eligible bump means exit 0, no branch, no PR (S1).
- AC-2: eligible bumps give one PR from `upgrade-<date>` with one commit that GitHub signs; nothing is pushed with `git push` (S2).
- AC-3: a same-day rerun with an open PR adds one more signed commit to that PR, and opens no second PR (S3).
- AC-4: after each commit, the run dispatches `test.yml`, and `live.yml` too when a live trigger file changed (S4).
- AC-5: no step waits for input, and no image rebuild runs (S5).
- AC-6: a major bump is applied like any other (S6).
- AC-7: the commit and the PR title are `feat(catalog): upgrade pins <date>`, so the next Release PR proposes a minor version (S7).

**What must not change.** `update` without `--no-rebuild` behaves as today, and all existing `test_update_*` tests pass unchanged. The release-age windows do not change. `mise run upgrade-pr` is untouched. `test.yml` still gates pull requests.

**How each criterion is proven.** S1 to S4 and S7 run `tools/pin-upgrade.sh` under pytest, in a temporary git repository with a local bare `origin`, and with stub `gh` and `harnessed` programs on `PATH` that log every call. S5 and S6 are pytest tests on the `update` command through typer's `CliRunner`. S8 is static tests on the workflow file. Then the gauntlet runs: the suite, ruff, pyright, shellcheck, coverage, scoped mutation testing on `launcher.py`, and the adversarial review. `live.yml` runs on the PR because `launcher.py` changes. The real scheduled run cannot be dispatched before merge (see Known limits).

**Open decisions.** None. Ruled (mcrowe, 2026-10-12): the rebuild is skipped by a `--no-rebuild` flag; a harness release younger than 2 days is applied as today; the signed commit is made with `gh api graphql`; `mise run upgrade-pr` is unchanged; a same-day run after that day's PR merged skips until the next run.

## Orientation
- Change: add `tools/pin-upgrade.sh` and `.github/workflows/pin-upgrade.yml`, add `--no-rebuild` to `harnessed update`, and delete `pin-check.yml`.
- Why: pins move forward with no manual step, and only when something moved.
- Touches: see the Touches list.
- Decide: Decide 1, Decide 2, Decide 3, Decide 4, Decide 5.
- Decided: Decide 1 A, `--no-rebuild` flag, governs S5; Decide 2 A, a harness release younger than 2 days is applied, governs Terms (Eligible bump) and S6.1; Decide 3 A, `gh api graphql`, governs Terms (API commit) and S2; Decide 4 A, `mise run upgrade-pr` unchanged, governs Must NOT; Decide 5 B, skip after a same-day merge, governs S3.5 (mcrowe, 2026-10-12).
- Tier: 2 — a scheduled job that holds a write token and opens PRs, plus one new CLI flag.
- Issue: GH-582
- Isolation: worktree `gh-582-pin-upgrades`, branch `GH-582`.

Failure model (Tier 2):
- The run pushes a commit with `git push`, which is unsigned, so the main ruleset refuses the merge. Caught by S2.3.
- The run opens a PR with no change, or opens a second PR on the same day. Caught by S1.1, S3.1 and S3.2.
- The run rebuilds images or waits on a prompt until the job times out. Caught by S5.1 to S5.4.
- The run's live trigger list drifts from `live.yml`. Caught by S4.3.
- The workflow gains a `pull_request` trigger, so a third-party release fails an unrelated PR. Caught by S8.1.

### Terms
- **The run**: one execution of `tools/pin-upgrade.sh` from the repository root, with `GH_TOKEN` and `GITHUB_REPOSITORY` set.
- **`<date>`**: the UTC date when the run starts, from `date -u +%F`, for example `2026-10-13`.
- **The branch**: `upgrade-<date>`.
- **Eligible bump**: a finding in `report.stale` of `harnessed update`, as `src/harnessed/update.py` `_select` decides. A non-harness release is eligible when its age in days is `>= 7.0` (the default 10080 minutes). A harness release is eligible at any age: when every newer harness release is younger than 2 days, the newest is offered with `fresh = True`, and `--yes` applies it, as `update` does today (Decide 2 A, mcrowe, 2026-10-12). This is how the plan reads the story constraint "Harness pins keep their 2-day window": the window stays the preference it is today, not a gate.
- **Changed files**: the output of `git diff --cached --name-only` after `git add catalog mise.toml`.
- **Live trigger file**: a path that matches one of these patterns, the same list as the `case` in `.github/workflows/live.yml` job `changes`: `catalog/base/Dockerfile.harnessed-*`, `catalog/base/harnessed-start`, `src/harnessed/volumes.py`, `src/harnessed/launcher.py`, `src/harnessed/paths.py`, `.github/workflows/live.yml`.
- **API commit**: one call of the GitHub GraphQL mutation `createCommitOnBranch`, made with `GITHUB_TOKEN`. GitHub signs such a commit as github-actions[bot]. Its input holds `branch.repositoryNameWithOwner`, `branch.branchName`, `expectedHeadOid`, `message.headline`, and `fileChanges.additions`, one entry per changed file with the path and the base64 of its staged content.
- **Stub `gh`**: a test program on `PATH` that appends its argv, one JSON array per line, to `$STUB_LOG`. It answers from files the test writes: `gh api repos/<repo>/git/ref/heads/<branch>` prints `{"object":{"sha":"<sha>"}}` when `$STUB_DIR/branch-sha` exists, or else exits 1 with `HTTP 404`. `gh pr list --head <branch> --state open --json number` prints `$STUB_DIR/open-prs`, or `[]` when that file is absent. `gh pr list --head <branch> --state merged --json number` prints `$STUB_DIR/merged-prs`, or `[]` when that file is absent. `gh api graphql` saves the request body it reads from `--input` to `$STUB_DIR/graphql-<n>.json` and prints `{"data":{"createCommitOnBranch":{"commit":{"oid":"<40 hex>"}}}}`. `gh workflow run` exits 1 when `$STUB_DIR/fail-workflow-run` exists. Every other call prints nothing and exits 0.
- **Stub `harnessed`**: a test program on `PATH` that appends to `$STUB_LOG` one JSON array of `"harnessed"`, its arguments, and the output of `git rev-parse HEAD` in the working tree. It reads its stdin to the end. Then it copies each file under `$STUB_DIR/writes/` over the file at the same relative path in the working tree, and removes each path listed in `$STUB_DIR/deletes`, one relative path per line. With neither, it changes nothing.
- **Test repository**: a temporary git repository with one commit on `main`, holding `catalog/recipes/pulumi/recipe.yaml` and `mise.toml`. Its `origin` is a local bare repository with the same `main`.

## Scenarios
### S1. Nothing eligible, nothing created (AC-1)
- S1.1 Given the test repository and a stub `harnessed` with no `writes/`, when the run runs, then it exits 0, prints `no pin changed; nothing to do`, and the stub log holds no `gh api graphql`, no `gh api -X POST repos/<repo>/git/refs`, no `gh pr create`, and no `gh workflow run`.
- S1.2 (boundary) Given a recipe pin `npm:x@1.0.0` and a resolver that offers `2.0.0` published exactly 7.0 days before `now`, when `update.build_report` runs with the default window, then the finding is in `report.stale`, not in `report.cooling`.
- S1.3 (negative) Given S1.1, when the run ends, then the bare `origin` holds no ref named `upgrade-<date>`.

### S2. Eligible bumps give one signed-commit PR (AC-2)
- S2.1 Given the test repository with no `branch-sha` file and a stub `harnessed` whose `writes/` changes `catalog/recipes/pulumi/recipe.yaml`, when the run runs, then the stub log shows, in this order: one `gh api -X POST repos/<repo>/git/refs` with `ref=refs/heads/upgrade-<date>` and `sha=` the `main` head, one `gh api graphql`, and one `gh pr create --base main --head upgrade-<date>`. The run exits 0.
- S2.2 Given S2.1, then the saved GraphQL body has `expectedHeadOid` equal to the `main` head, `branch.branchName` equal to `upgrade-<date>`, and one `additions` entry whose `path` is `catalog/recipes/pulumi/recipe.yaml` and whose `contents` decodes to the file the stub wrote.
- S2.3 (negative) Given S2.1, when the run ends, then the bare `origin` holds no ref `upgrade-<date>`, which proves no `git push` ran. The script holds no `git push` and no `git commit` (asserted on its text).
- S2.4 (boundary) Given `writes/` changes two files, `catalog/recipes/pulumi/recipe.yaml` and `mise.toml`, when the run runs, then the stub log holds exactly one `gh api graphql`, and its `additions` hold both paths.
- S2.5 (negative, safety guard for AC-2: the API commit in Terms carries additions only, so a deletion would be dropped silently) Given `$STUB_DIR/deletes` lists `catalog/recipes/pulumi/recipe.yaml`, so the stub `harnessed` removes it and `git add catalog mise.toml` stages the deletion, when the run runs, then it exits 1, prints `pin-upgrade: refusing a deletion: <path>`, and calls no `gh api graphql`.

### S3. A same-day rerun adds to the open PR (AC-3)
- S3.1 Given `upgrade-<date>` exists on the bare `origin` at commit B (one commit after `main`), `branch-sha` holds B, `open-prs` holds `[{"number":7}]`, and `writes/` changes a file, when the run runs, then the stub log's `harnessed` line ends with B, which proves the run checked out `origin/upgrade-<date>` before it ran `harnessed`; the saved GraphQL body has `expectedHeadOid` = B, and the stub log holds no `git/refs` POST and no `gh pr create`.
- S3.2 (boundary) Given S3.1 but with no `writes/`, when the run runs, then it exits 0, prints `no pin changed; nothing to do`, and the stub log holds no `gh api graphql`, no `gh pr create` and no `gh workflow run`.
- S3.3 (negative) Given S3.1, when the run ends, then the bare `origin` still has `upgrade-<date>` at B, so the earlier commit was not rewritten.
- S3.5 (negative) Given `merged-prs` holds `[{"number":6}]` and `writes/` changes a file, when the run runs, then it exits 0, prints `upgrade-<date> already merged today; the next run picks up new bumps`, and the stub log holds no `harnessed` line, no `gh api graphql`, no `gh pr create` and no `gh workflow run` (Decide 5 B, mcrowe, 2026-10-12).
- S3.4 (boundary) Given the branch exists (`branch-sha` holds B) and `open-prs` holds `[]`, and `writes/` changes a file, when the run runs, then it makes the API commit on B and calls `gh pr create` once.

### S4. Checks start on the PR (AC-4)
- S4.1 Given S2.1, when the run ends, then the stub log holds `gh workflow run test.yml --ref upgrade-<date>` after the `gh api graphql`, and no `gh workflow run live.yml`.
- S4.2 (boundary) Given `writes/` changes `catalog/base/Dockerfile.harnessed-base`, a live trigger file, when the run runs, then the stub log holds both `gh workflow run test.yml --ref upgrade-<date>` and `gh workflow run live.yml --ref upgrade-<date>`.
- S4.3 (negative) Given `tools/pin-upgrade.sh` and `.github/workflows/live.yml`, when a test reads the patterns in the script's `LIVE_TRIGGERS` and the patterns in the `case` of live.yml job `changes`, then the two sets are equal. A pattern in one and not the other fails the test.
- S4.4 Given S3.1, when the run ends, then the stub log holds `gh workflow run test.yml --ref upgrade-<date>`, because the new commit has no check run.
- S4.5 (negative) Given S2.1 and a stub `gh` that exits 1 on `gh workflow run` (the test writes `$STUB_DIR/fail-workflow-run`), when the run runs, then it exits non-zero and prints the failed `gh workflow run` command, so a PR with no check started never ends in a green run.

### S5. No prompt, no rebuild (AC-5)
- S5.1 Given a catalog with an unpinnable harness agent (claude) and one stale recipe pin, when `harnessed update --yes --no-rebuild` runs through `CliRunner`, then the stale pin is rewritten, `_runtime`, `_built_pairs_for` and `_refresh_unpinnable_harness` are never called, the exit code is 0, and stdout holds `skipped the unpinnable-harness rebuild (--no-rebuild)`.
- S5.2 (boundary) Given S5.1 with `--no-rebuild` left out, when `harnessed update --yes` runs, then `_refresh_unpinnable_harness` is called once for claude, as today.
- S5.3 (negative) Given one stale recipe pin, when `harnessed update` runs without `--yes` through `CliRunner` with `input=""`, then it exits non-zero within the test (no wait for input) and the pin is unchanged.
- S5.4 Given S2.1 with `HARNESSED_CMD` set to the stub `harnessed`, then the stub log's `harnessed` line holds exactly the arguments `update --yes --no-rebuild`, and the stub read EOF on stdin at once, because the script runs it with `< /dev/null`.

### S6. Major bumps are applied (AC-6)
- S6.1 Given a catalog with a harness agent pin at `1.4.0` whose resolver offers `2.0.0` published 3 days ago, and a recipe pin `npm:x@1.0.0` whose resolver offers `1.5.0` published 10 days ago, when `harnessed update --yes --no-rebuild` runs, then both files hold the new versions, `2.0.0` and `1.5.0`.
- S6.2 (negative) Given S6.1, then stdout holds no line `Left N pin(s) unchanged`.
- S6.4 (boundary) Given a harness agent pin at `1.4.0` whose resolver offers `1.5.0` published 1 day ago, when `harnessed update --yes --no-rebuild` runs, then the agent file holds `1.5.0` (Decide 2 A, mcrowe, 2026-10-12).
- S6.3 (negative) The script passes no flag that filters majors: S5.4 pins its `harnessed` arguments to exactly `update --yes --no-rebuild`, so no `--fail-on` or other filter can reach the run.

### S7. The PR is a feat (AC-7)
- S7.1 Given S2.1, then the saved GraphQL body has `message.headline` = `feat(catalog): upgrade pins <date>`, and the `gh pr create` argv holds `--title` `feat(catalog): upgrade pins <date>`.
- S7.2 (negative) Given S7.1, when a test matches that title against the `pattern=` regex in `.github/workflows/pr-title.yml`, then it matches, and the script text holds no `chore(`.
- S7.3 Given `release-please-config.json` and `.release-please-manifest.json`, when a test reads them, then `bump-minor-pre-major` is `true` and the version is below `1.0.0`. Under that setting release-please treats a `feat` commit as a minor bump: 0.2.1 becomes 0.3.0.

### S8. The workflow file (supports AC-1 to AC-5)
- S8.1 (negative) Given `.github/workflows/pin-upgrade.yml`, then its triggers are exactly `schedule` and `workflow_dispatch`: no `pull_request`, `pull_request_target` or `push`.
- S8.2 Given S8.1, then the schedule cron is `0 6 */2 * *`.
- S8.3 Given S8.1, then every `uses:` value ends in `@` and 40 hex characters, the job has a `timeout-minutes` of 30 or less, `permissions` is exactly `contents: write`, `pull-requests: write`, `actions: write`, and a step `uses` mise (so a `tools:` entry with no backend prefix resolves).
- S8.4 Given S8.1, then a step runs `tools/pin-upgrade.sh` with `GH_TOKEN` set from `github.token`.
- S8.5 (negative) Given the repository, then `.github/workflows/pin-check.yml` does not exist, and `test.yml` still has the `pull_request` trigger.

## Must NOT
- Existing `tests/test_update_*.py` tests pass unchanged. → full suite.
- `update` without `--no-rebuild` keeps today's rebuild offer. → S5.2.
- `DEFAULT_MINIMUM_RELEASE_AGE_MINUTES` and `HARNESS_MINIMUM_RELEASE_AGE_MINUTES` do not change. → full suite (`test_update_cooldown.py`).
- `--check` writes nothing and never rebuilds. → existing `test_check_writes_nothing`, `test_check_never_rebuilds`.
- `mise run upgrade-pr` is unchanged (Decide 4 A, mcrowe, 2026-10-12). → diff review.
- No commit reaches a branch through `git push` in the workflow. → S2.3.
- The live trigger list stays one list. → S4.3.

## Touches
- `tools/pin-upgrade.sh` (new): the run. `set -euo pipefail`; `HARNESSED_CMD` defaults to `uv run --extra dev harnessed`; `LIVE_TRIGGERS` holds the live trigger patterns.
- `.github/workflows/pin-upgrade.yml` (new): schedule `0 6 */2 * *` and `workflow_dispatch`; checkout, setup-uv, mise, then `tools/pin-upgrade.sh`. Every action pinned to a SHA.
- `.github/workflows/pin-check.yml`: deleted.
- `src/harnessed/launcher.py`: `update_pins` gets `--no-rebuild`. When it is set, `_offer_unpinnable_refresh` is not called and one line is printed.
- `tests/test_ci_pin_check_workflow.py`: deleted. Its trigger rules move to the new workflow test.
- `tests/test_ci_pin_upgrade_workflow.py` (new): S4.3, S7.2, S7.3, S8.
- `tests/test_pin_upgrade_script.py` (new): S1.1, S1.3, S2, S3, S4.1, S4.2, S4.4, S5.4, S7.1.
- `tests/test_update_cli.py`: new tests S5.1 to S5.3, S6.
- `tests/test_update_cooldown.py`: new test S1.2.
- `tools/preflight.sh`: the header comment line that names `pin-check.yml` is replaced with one that names `pin-upgrade.yml`.
- `CLAUDE.md` §Tests: the sentence "They are one filter written twice" names `tools/pin-upgrade.sh` as the third copy, guarded by S4.3.

## Known limits
- The workflow cannot be dispatched before it is on `main`, because `workflow_dispatch` needs the file on the default branch. The first real run is after merge; its log and PR go into a follow-up comment on GH-582.
- A dispatched `test.yml` reports the `pytest` check on the branch head. `release-please.yml` relies on the same dispatch for its Release PR, which has merged under the same ruleset (v0.2.1). The first upgrade PR confirms it for this workflow.
- `lint.yml` and `pr-title.yml` do not run on the upgrade PR, because a PR opened with `GITHUB_TOKEN` starts no workflows. Only `pytest` is a required check on `main`, and S4 dispatches it.
- S7.3 proves the release-please setting, not a release. The 0.3.0 proposal is seen after the first upgrade PR merges.

## Verification contract
- Full suite: `tools/run-tests.sh`, zero new failures against the baseline.
- Lint: ruff and pyright at zero new findings; `shellcheck tools/pin-upgrade.sh` clean.
- Coverage on changed Python lines: 80% or more.
- Mutation: scoped to `update_pins` in `launcher.py` (manual mutants, because mutmut skips typer commands) and to `tools/pin-upgrade.sh` by hand-made mutants on the deletion guard, the no-change exit and the live match.
- Real execution: `harnessed update --yes --no-rebuild` on a scratch copy of the catalog under an isolated `XDG_DATA_HOME`, stdin from `/dev/null`; it ends with no prompt and no image build.
- Adversarial review: one round, two at most.
