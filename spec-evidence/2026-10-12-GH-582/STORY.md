---
id: GH-582
type: feature
source:
  tracker: github
  external_id: GH-582
  url: https://github.com/drmikecrowe/harnessed/issues/582
  version: "unavailable: show returns no updated stamp"
---
# Automated pin upgrades every other day: 7-day gate, PR only on change, non-interactive upgrade task

## Description
Who: the harnessed maintainer, who now runs `mise run upgrade-pr` by hand to move catalog pins forward.
What: a scheduled GitHub workflow runs the pin upgrade every other day with no prompts. It accepts every eligible bump, major ones included. It opens a PR only when a pin moved, and that PR is typed `feat` so that merging it produces a minor release. A human reviews and merges the PR. It replaces `pin-check.yml`.
Done looks like: AC-1 to AC-7 below hold on a scheduled run on GitHub's runner.
Example: a run on 2026-10-13 finds that `pulumi@3.266.0` (catalog/recipes/pulumi/recipe.yaml) has a newer release published 8 days earlier. The run creates branch `upgrade-2026-10-13` with one signed commit `feat(catalog): upgrade pins 2026-10-13`, opens one PR with that title, and dispatches `test.yml` on it. After the merge, release-please's next Release PR proposes 0.3.0 from 0.2.1. If that release were 3 days old, the run would create no branch and no PR.
Context: today `upgrade-pr` never runs `harnessed update`. It commits whatever is dirty in `catalog/` and `mise.toml` as `chore(catalog)`, then always pushes and runs `gh pr create`. `harnessed update --yes` rebuilds images for claude and antigravity in apply mode, and a runner has no podman (#563). `pin-check.yml` runs weekly with `--check --fail-on major` and writes nothing (#469).
Drafted by the assistant from the author's text; approved by the author 2026-10-12.

## Acceptance criteria
- AC-1: When a scheduled run finds no bump past its release-age window, the run exits 0; boundary: a release exactly at the window edge counts as eligible, as `harnessed update` already decides; negative: no `upgrade-<date>` branch is pushed and no PR is opened.
- AC-2: When a scheduled run finds one or more eligible bumps, it opens exactly one PR from `upgrade-<date>` holding a commit signed through GITHUB_TOKEN API commits; boundary: several bumps found in one run land in one commit; negative: no unsigned commit is pushed, and no second PR opens.
- AC-3: When a PR for that day's branch is already open, a rerun that finds new bumps adds one more signed commit to that PR; boundary: a second `workflow_dispatch` on the same day gives a PR with two commits; negative: no second PR for the same date, and the earlier commit is not rewritten.
- AC-4: After the PR opens, the run dispatches `test.yml` on the branch, and also `live.yml` when the diff touches a live trigger file listed in CLAUDE.md §Tests; boundary: a diff of only `mise.toml` dispatches `test.yml` alone; negative: the PR is never left with no required check started.
- AC-5: No step of the run waits for input, and no step runs an image rebuild; boundary: the run calls `harnessed update --yes` with the rebuild suppressed; negative: a step that would prompt makes the run fail, never hang until timeout.
- AC-6: When an eligible bump crosses a major version, harness pin or not, the run applies it like any other bump; boundary: a harness pin going from one major to the next lands in the same commit as minor bumps; negative: the run holds back no eligible bump because it is major.
- AC-7: The commit and the PR title use `feat(catalog): upgrade pins <date>`, so merging the PR adds a minor bump to release-please's next Release PR; boundary: on 0.2.1 the Release PR proposes 0.3.0; negative: the run never uses the `chore` type, which starts no release.

## Constraints
- New `.github/workflows/pin-upgrade.yml`: `schedule` every other day (`0 6 */2 * *`) plus `workflow_dispatch`, every action pinned to a SHA (#288).
- `.github/workflows/pin-check.yml` is deleted.
- Commits use the GITHUB_TOKEN API commit path that `release-please.yml` uses (#577). A PAT's commits are unsigned.
- The PR title passes the `pr-title.yml` pattern.
- Non-harness pins keep the 7-day default (`--minimum-release-age`, 10080 minutes). Harness pins keep their 2-day window, so the run passes no explicit `--minimum-release-age`.

## Author notes
- SR-DEFER: "a flag on `update` (for example `--no-rebuild`), or pins-only mode when not on a TTY". engineering checks at the plan review
