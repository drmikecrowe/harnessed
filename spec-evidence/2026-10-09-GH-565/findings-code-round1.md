{
  "clean_claims": [
    "src/harnessed/launchscript.py — write_globals, remove_globals, _is_ours_to_touch, _global_body, parse_global_name, global_name: FIFO/symlink/path-traversal guards are present and correct; shlex.join prevents injection through stack and harness names; the sentinel read limit is correctly applied",
    "src/harnessed/aoe.py — _exec_tokens refactor: correctly returns None for every early-exit path; _replays_stack dual-format check (old --stack flag and new global-name exec) is logically correct",
    "src/harnessed/launcher.py — _is_retired_shim: correctly reads the exec line and checks its exact token structure; symlink guard is first; the ValueError early-return is the only path that exits the loop before the return",
    "src/harnessed/launchscript.py _body — args.index('--stack') is safe: aoe.command_for always inserts --stack at position 4; the first occurrence is always the real flag, not a value"
  ],
  "finding": [
    {
      "file": "src/harnessed/launcher.py",
      "line": 5333,
      "severity": "advisory",
      "rule": "none",
      "defect": "The `names` set passed to `rows_referencing` is built from all verbs in `_GLOBAL_VERB_SUFFIX`, not from the `removed` list returned by `remove_globals`; launchers that were refused (foreign files not deleted) are included, so rows that exec a refused-but-still-present launcher are reported as 'aoe row still references a removed launcher' when the row is actually functional.",
      "trigger": "`harnessed uninstall <stack> <harness>` when at least one target launcher is refused (a foreign file exists at that path with no sentinel); an aoe row points at the refused (still-existing) launcher.",
      "consequence": "User sees a false warning naming a working row as broken and may delete it, which would break that aoe entry unnecessarily. The SPEC S5.2 and S5.3 together imply refused launchers are reported separately from row warnings, but the implementation conflates them."
    }
  ],
  "hunch": [
    {
      "file": "src/harnessed/launchscript.py",
      "line": 283,
      "rule": "none",
      "defect": "`args.index(aoe._STACK_FLAG[0])` in `_body` raises `ValueError` with no handler if `--stack` is absent from the `command_for` output; the safety depends entirely on `aoe.command_for` never omitting it.",
      "consequence": "If `command_for` is ever changed to omit `--stack` (e.g. for a future verb that does not need it), `write` would raise inside its `try` block and return None silently — the launch would proceed without a local launcher, which is the safe outcome, but the root cause would be invisible."
    }
  ],
  "coverage": {
    "calls_used": "7/10",
    "hunts_not_reached": [
      "1 (gate command comparison — gauntlet-layers.json not read)",
      "6 (invariants in docstrings/guards within 50 lines of the change — partially covered by reading the source but not exhaustively)",
      "8 (EVIDENCE report summary vs tables — EVIDENCE.md not read)"
    ],
    "sites_not_opened": [
      "src/harnessed/aoe.py:320-340 (command_for body — confirmed via grep that --stack is always present, but the full function body was not read)"
    ]
  }
}
