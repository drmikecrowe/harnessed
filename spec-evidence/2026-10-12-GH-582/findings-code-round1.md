{
  "clean_claims": [
    "src/harnessed/launcher.py update_pins hunk: the --no-rebuild branch only guards _offer_unpinnable_refresh, and --check still returns earlier as before (read in the diff only, not at HEAD)",
    ".github/workflows/pin-upgrade.yml: triggers, SHA-pinned actions, permissions and timeout match S8; test.yml and live.yml both carry workflow_dispatch (grep), so the script's dispatches have a target",
    "tools/pin-upgrade.sh control flow: the merged-skip, no-change exit, deletion guard, ref-before-commit and dispatch-failure paths all match S1 to S4 as written"
  ],
  "finding": [
    {
      "file": "/home/mcrowe/Programming/Personal/harnessed/gh-582-pin-upgrades/tests/test_update_cli.py",
      "line": 759,
      "severity": "advisory",
      "rule": "none",
      "defect": "SPEC S5.2 (update --yes without --no-rebuild still calls _refresh_unpinnable_harness once) has no test in the TestUnattendedRun class this diff adds. S4.1's 'no live.yml dispatch' assertion is also missing from test_s4_1.",
      "trigger": "Make the --no-rebuild branch unconditional, or always dispatch live.yml. The new tests still pass.",
      "consequence": "Two 'Must NOT' regressions (the default rebuild offer is lost; a needless live run starts on every upgrade PR) are unguarded unless an existing test happens to cover them. I did not check whether one does."
    }
  ],
  "hunch": [
    {
      "file": "/home/mcrowe/Programming/Personal/harnessed/gh-582-pin-upgrades/tools/pin-upgrade.sh",
      "line": 901,
      "rule": "none",
      "defect": "The workflow checks out with persist-credentials: false, then the script runs `git fetch origin \"$branch\"`. That fetch has no credentials.",
      "consequence": "On a private repo, or if the repo is not public, the same-day rerun path (on_remote=true) fails at the fetch. The stub tests use a local origin, so they cannot see this."
    },
    {
      "file": "/home/mcrowe/Programming/Personal/harnessed/gh-582-pin-upgrades/tools/pin-upgrade.sh",
      "line": 905,
      "rule": "none",
      "defect": "A new branch is created at `git rev-parse HEAD`, which is the dispatched ref, not main. The PR base is hard-coded to main.",
      "consequence": "A manual workflow_dispatch from a non-main ref would put that ref's unrelated commits into the upgrade PR."
    },
    {
      "file": "/home/mcrowe/Programming/Personal/harnessed/gh-582-pin-upgrades/tools/pin-upgrade.sh",
      "line": 924,
      "rule": "none",
      "defect": "`changed` comes from `git diff --name-only`, which quotes paths with special characters, and the loop feeds each name to `git show \":$f\"`. The API commit also carries contents only, so file mode changes are dropped.",
      "consequence": "A pin file with a non-ASCII or special-character path would fail the run. An executable-bit change would be silently lost."
    }
  ],
  "coverage": {
    "calls_used": "2/10",
    "hunts_not_reached": [
      "1 (gate argument comparison: lint.yml and test.yml not opened, shellcheck cleanliness of the new script unverified)",
      "2 (callers of update_pins or _offer_unpinnable_refresh outside the diff)",
      "8",
      "10"
    ],
    "sites_not_opened": [
      "/home/mcrowe/Programming/Personal/harnessed/gh-582-pin-upgrades/.github/workflows/live.yml:83",
      "/home/mcrowe/Programming/Personal/harnessed/gh-582-pin-upgrades/.github/workflows/lint.yml",
      "/home/mcrowe/Programming/Personal/harnessed/gh-582-pin-upgrades/tests/test_update_cli.py (existing S5.2 coverage)"
    ]
  }
}
