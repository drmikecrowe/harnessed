# Decisions — GH-582

## Setup plan
- Isolation: worktree `gh-582-pin-upgrades`, branch `GH-582`, made from `main` at 6f26582.
- Git: signed commits (`git commit -S`) in this worktree; no commit to `main`.
- New files: `tools/pin-upgrade.sh`, `.github/workflows/pin-upgrade.yml`, `tests/test_ci_pin_upgrade_workflow.py`, `tests/test_pin_upgrade_script.py`.
- Deleted files: `.github/workflows/pin-check.yml`, `tests/test_ci_pin_check_workflow.py`.
- New dependencies: none in the repository. The workflow uses `jq` and `gh`, which `ubuntu-latest` ships. Decide 3 option B would add one action.

## Tooling audit
| Layer | Declared by the project | Status if nothing is added |
|---|---|---|
| Merge gate parity | `main` ruleset requires `pytest` and signed commits (`gh api repos/drmikecrowe/harnessed/rules/branches/main`). `lint.yml`: ruff, pyright, shellcheck on `git ls-files '*.sh'`. `pr-title.yml`: title regex. `live.yml`: container layer on trigger files. | runs |
| Full test suite | `tools/run-tests.sh` | runs |
| Static types | pyright pinned in `mise.toml` | runs |
| Lint + format | ruff, shellcheck 0.11.0 (`mise.toml`) | runs |
| Changed-line coverage | `tools/gauntlet-layers.json` | runs |
| Mutation testing | mutmut; skips typer commands, so `update_pins` needs manual mutants | runs, manual for the CLI and the shell script |
| Property-based tests | hypothesis in dev extras | N-A: no parser or round trip changes |
| Real execution | `harnessed update` on a scratch catalog | runs; the workflow itself only after merge |
| Supply chain & secrets | gitleaks | runs |
| Adversarial review | spec-evidence-adversary | runs |

## Facts verified
- `harnessed update --yes` calls `_offer_unpinnable_refresh(report, yes)` before the bumps (`src/harnessed/launcher.py` `update_pins`). A reachable runtime rebuilds claude and antigravity; only an unreachable one degrades to a warning. Whether `ubuntu-latest` carries a runtime was not checked in this session; the story says it has no podman (#563). `--no-rebuild` makes the run the same either way.
- `_select` in `src/harnessed/update.py`: a non-harness release is eligible when `age_days >= min_days`, so exactly 7.0 days is eligible. Existing `test_the_boundary_is_the_configured_window` covers 6.9 and 7.1 only.
- `_select`: a harness pin never waits. When every newer harness release is younger than 2 days, the newest is offered anyway with `fresh = True`, and `--yes` applies it (owner decision 2026-09-23, quoted in the docstring).
- `typer.confirm` with empty stdin raises Abort, so `update` without `--yes` exits non-zero instead of waiting.
- `release-please.yml` explains why GITHUB_TOKEN API commits are signed and a PAT's are not, and dispatches `test.yml` on its PR branch.
- The `main` ruleset requires only the `pytest` status check.
- `live.yml` treats any non-`pull_request` event, `workflow_dispatch` included, as "run the live layer".
- `pulumi@3.266.0` is in `catalog/recipes/pulumi/recipe.yaml`.
- `release-please-config.json` sets `bump-minor-pre-major: true`; `.release-please-manifest.json` holds 0.2.1.
- The repository is public, so `git fetch origin upgrade-<date>` needs no credential.
- `tests/test_ci_pin_check_workflow.py` encodes the pin-check trigger rules (no `pull_request`/`push`, a schedule, `workflow_dispatch`, mise installed). S8 carries them to the new workflow.
- `harnessed update` never writes a live trigger file today: Dockerfile pins are reported as unresolved and never rewritten. S4.2 still covers the path, because AC-4 asks for it.

## Restatements
- AC-1's "no bump past its release-age window" is read as `report.stale` is empty. For harness pins that depends on Decide 2.
- AC-3 is read for an open PR only. A same-day run after a merge is in Known limits.
- Judge gap from Gate 1 round 2: a rerun with an open PR and no new bump exits 0 and touches nothing (S3.2).

## Decide calls

### Decide 1. How does the run skip the image rebuild?
- Evidence: `src/harnessed/launcher.py` `update_pins` calls `_offer_unpinnable_refresh(report, yes)`; story Author note SR-DEFER.
- A. A `--no-rebuild` flag on `update`. Cost: one new flag, explicit in the workflow, testable through `CliRunner`.
- B. Pins-only mode whenever stdin is not a TTY (`_can_prompt` false). Cost: no flag, but it changes `update --yes` for every piped or scripted caller, silently.
- Default: A.
- Ruling: A, `--no-rebuild` flag (mcrowe, 2026-10-12)

### Decide 2. Does the run apply a harness release younger than 2 days?
- Evidence: `src/harnessed/update.py` `_select`, the `if pin.harness:` branch; existing `test_a_three_day_old_harness_release_is_bumped`, `test_a_fresh_harness_bump_is_named_with_its_age`.
- A. Yes, as today: the 2-day window is a preference, and `--yes` applies a `fresh` harness release. Cost: a harness release hours old can land in the PR; a person still reviews before merge.
- B. No: the run holds harness releases until they are 2 days old. Cost: a new flag that turns the harness window into a gate, plus tests.
- Default: A.
- Ruling: A, apply as today (mcrowe, 2026-10-12)

### Decide 3. How is the signed commit made?
- Evidence: `.github/workflows/release-please.yml` header comment; `main` ruleset `required_signatures`.
- A. `gh api graphql` with `createCommitOnBranch`, built with `jq` inside `tools/pin-upgrade.sh`. Cost: about 30 lines of shell; no new dependency.
- B. A third-party action that makes API commits, pinned to a SHA. Cost: a new dependency that runs with a write token.
- Default: A.
- Ruling: A, `gh api graphql` (mcrowe, 2026-10-12)

### Decide 4. Does `mise run upgrade-pr` change?
- Evidence: `mise.toml` `[tasks.upgrade-pr]` commits as `chore(catalog)` and never runs `harnessed update`. No acceptance criterion names it.
- A. Leave it unchanged. Cost: the manual path keeps `chore` commits, which start no release.
- B. Make it call `tools/pin-upgrade.sh`. Cost: the manual run then makes API commits as github-actions[bot] and needs a token with write scope locally.
- Default: A.
- Ruling: A, leave unchanged (mcrowe, 2026-10-12)

## Intent review (spec-intent.md)
- Accepted: the runner-podman sentence is reworded to the story's claim (Summary).
- Accepted: S4.5 added; a failed `gh workflow run` fails the run.
- Accepted: S6.3 names S5.4 as the guard that the script passes no major filter.
- Accepted in part: S2.5 is marked a safety guard for AC-2. Declined: closing Decide 2 by assumption. Both options keep the 2-day window; they differ on whether it is a gate, which the story does not say, so the author rules it.
- Accepted: the merged-same-day edge goes to the author as Decide 5.

### Decide 5. A same-day run after that day's PR merged
- Evidence: SPEC Known limits; story AC-3 negative "no second PR for the same date".
- A. Open a new PR on `upgrade-<date>`. Cost: two PRs share one date in rare cases.
- B. Skip the run when a merged PR for `upgrade-<date>` exists; the next scheduled run picks the bump up. Cost: one more `gh pr list --state merged` call and a scenario.
- Default: B, because it keeps the story's negative literally true.
- Ruling: B, skip until the next run (mcrowe, 2026-10-12)

## Intent review, round 2
- Accepted: S6.4 adds a harness release 1 day old, so the Decide 2 reading is tested.
- Accepted: Known limits cite the release-please precedent for a dispatched `pytest` check.
- Declined: an end-to-end edge test in the script. The script does not choose bumps; `update` does, and S1.2 pins `update`'s edge.
- Declined: S2.5 and S3.5 as unapproved scope. mcrowe is the story author and ruled Decide 5 B; S2.5 is marked as a safety guard for AC-2.
- Declined: a Summary note on `live.yml`. The Summary already says `live.yml` runs because `launcher.py` changes.

## Revision log
- Revision 1 (2026-10-12): first draft.
- Revision 2 (2026-10-12): intent review folded in; Decide 5 added.
- Revision 3 (2026-10-12): Decides 1 to 5 ruled; S3.5 added for Decide 5; the merged-same-day Known limit removed.
- Revision 4 (2026-10-12): Gate 1a round 1 PR-REFERENT fixed: the stub `harnessed` gains `$STUB_DIR/deletes` (S2.5). Judge gaps closed: the stub logs `git rev-parse HEAD` so S3.1 observes the checkout order; Terms states how Decide 2 reads the story's 2-day constraint.
- Revision 5 (2026-10-12): intent review round 2 folded in (S6.4, Known limits).
- Revision 6 (2026-10-12, after PR #593 review): the workflow gains `concurrency: {group: pin-upgrade, cancel-in-progress: false}` and a job guard `if: github.ref == 'refs/heads/main'`, each with a test in `tests/test_ci_pin_upgrade_workflow.py`. Both close adversary hunches the bot review raised again. EVIDENCE.md describes 04d6cea and is not rewritten; the gates graded it. The review fix and its gauntlet run are recorded here and in the PR threads.
- Revision 7 (2026-10-12, PR #593 second review): the deletion guard names every refused path (new test `test_every_refused_deletion_is_named`). Declined: rebasing a leftover same-day branch onto current main. The concurrency group removes the overlap race, and a moved ref makes the commit fail closed; the remaining case (a run dies between the ref and the commit, then a same-day rerun builds on that base) is a known limit.
- Revision 8 (2026-10-12, PR #593 third review): a closed-but-unmerged PR for today now skips the run as a merged one does (Decide 5 B widened; S3.5 parametrized over merged and closed). A ref the run created is deleted when the API commit fails, which closes the Revision 7 known limit. Mutants M18 to M21 killed.
- Revision 9 (2026-10-12, PR #593 fourth review): the run fails when `update` leaves a tracked file changed outside catalog/ and mise.toml; the HARNESSED_CMD quoting rule is documented. Declined with evidence: a merged PR whose branch was deleted is still found by `gh pr list --head` (checked on PR #581, branch fix-omp-acp-mcp deleted, listed as MERGED); GraphQL input size (the real run changed 13 small files); recovery after a failed `gh pr create` (the red run is the alert).
- Revision 10 (2026-10-12, PR #593 fifth review): the finished-PR check runs again just before the ref and commit; file contents reach jq through files, not argv (a 300 KB change now commits); the public-repo requirement of the anonymous fetch is documented in the script and the workflow.
- Revision 11 (2026-10-12, PR #593 sixth review): the failed-commit cleanup deletes the ref only while it still points at the sha the run created it with. Declined: dispatching test.yml on a rerun with no new pin, which approved S3.2 forbids; a failed dispatch already fails the run (S4.5).
