{
  "clean_claims": [
    "round-1 finding (false warning for refused-but-present launchers): fixed correctly in commit 5149831; `names = {target.name for target in removed}` uses only the removed set, and `test_only_removed_launchers_are_looked_up` in tests/test_launcher_install.py pins it",
    "src/harnessed/launchscript.py _body — stack_at / args[stack_at+2:] slice logic: correctly strips verb, harness, path, --stack, and stack-name; per-launch flags are preserved; empty-flag case produces the correct bare exec line",
    "src/harnessed/launcher.py uninstall_stack — names guard (`if names else []`) prevents an empty-set call to rows_referencing when nothing was removed",
    "src/harnessed/launchscript.py write_globals / remove_globals — symlink, sentinel, and path-traversal guards are present and consistent with write()"
  ],
  "finding": [
    {
      "file": "tests/test_aoe.py",
      "line": 1911,
      "severity": "advisory",
      "rule": "none",
      "defect": "SPEC scenario S4.4 ('when `harnessed rm default` runs, then every file in `~/.local/bin` is unchanged') has no test anywhere in the diff or the existing suite.",
      "trigger": "Any invocation of `harnessed rm <stack>` while global launchers exist in `~/.local/bin`.",
      "consequence": "The SPEC's own verification contract says 'S1 to S6 and every existing test | all pass'; S4.4 is unverified by test. The behavior is correct by code structure (forget_stack never touches `~/.local/bin`), but the Must NOT constraint 'Let `harnessed rm` touch host rows or any file in `~/.local/bin`' is not pinned by a test, so a future change to forget_stack could regress it silently."
    }
  ],
  "hunch": [
    {
      "file": "src/harnessed/launchscript.py",
      "line": 283,
      "rule": "none",
      "defect": "`args.index(aoe._STACK_FLAG[0])` in `_body` raises ValueError with no handler; `write` only catches OSError, so a ValueError propagates out to the caller in `_launch_host` or `container_run`, both of which have no enclosing handler for it.",
      "consequence": "If `aoe.command_for` ever omits `--stack` (currently it never does), a launch would crash rather than proceed without a local launcher; the 'never fatal' contract of `write` would be violated. No known trigger today."
    }
  ],
  "coverage": {
    "calls_used": "5/10",
    "hunts_not_reached": [
      "1 (gate commands in test.yml / lint.yml not compared against the manifest — budget exhausted after diff, SPEC, and key source reads)",
      "8 (EVIDENCE.md not read)",
      "10 (Documentation section — SPEC names README.md and the catalog skill page; both are touched in the diff and the section gives a reason for the wiki, so this is likely not a finding, but was not verified)"
    ],
    "sites_not_opened": [
      "src/harnessed/aoe.py:forget_stack and _kill_session bodies — confirmed by grep that no test covers S4.4, but the full forget_stack body was not read to verify it never touches ~/.local/bin",
      ".github/workflows/test.yml and lint.yml — gate command arguments not compared against gauntlet-layers.json entries"
    ]
  }
}
