{
  "clean_claims": [
    "src/harnessed/jsonmerge.py merge_claude_json, seed_claude_project and read_json_or_empty, as shown in diff.txt: on reading, S1.1 to S1.11 hold and the inputs are copied, not mutated.",
    "src/harnessed/hosthome.py _seed_host_claude_json and _seed_host_claude_project, as shown in diff.txt: S3.9 and S3.10 hold on reading. A non-dict or missing file is a no-op for the project seed, and the atomic write goes through a temp file and os.replace."
  ],
  "finding": [],
  "hunch": [
    {
      "file": "tests/test_launch_host.py",
      "line": 996,
      "rule": "none",
      "defect": "test_s3_9 monkeypatches `hosthome.os.replace`, but the diff adds no `hosthome` import to this test module. The module may already import it. I could not check.",
      "consequence": "A NameError would fail the test. Baseline-green evidence would show it, so this is probably fine."
    },
    {
      "file": "src/harnessed/hosthome.py",
      "line": 269,
      "rule": "none",
      "defect": "_write_json_atomic uses `json` and `os`, and the diff does not show those imports being added to hosthome.py. They are probably already imported.",
      "consequence": "If they are missing, every host claude launch raises NameError. The tests would catch it."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 3363,
      "rule": "none",
      "defect": "backend.isolated_auth is assigned only just before seed_auth, inside the materialize path. If another caller, for example a rebuild or resume path, calls HostBackend.seed_auth without going through that line, isolated_auth silently stays False and the host identity is written into an isolated stack. The only guard is a source-text test that checks the assignment comes before the first `backend.seed_auth(spec)`.",
      "consequence": "The host oauthAccount and userID leak into an isolated stack. I could not enumerate the other seed_auth callers because the tools were blocked."
    }
  ],
  "coverage": {
    "calls_used": "4/10",
    "hunts_not_reached": [
      "1 (gate commands against tools/gauntlet-layers.json, test.yml and lint.yml were not opened)",
      "2 (callers outside the diff of _share_host_claude_state, HostBackend( and _claude_config_seed_mount were not enumerated)",
      "3",
      "5",
      "6",
      "7",
      "8",
      "9 (the keep= parameter of _clear_host_home_except_runtime was not confirmed)",
      "10"
    ],
    "sites_not_opened": [
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/hosthome.py:_clear_host_home_except_runtime",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/launcher.py:_launch_host",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/tools/gauntlet-layers.json",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/test.yml",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/lint.yml"
    ],
    "tooling_note": "Gortex MCP integration failure. The Gortex PreToolUse hook blocked Grep and Read on src/, and no Gortex tools are in my callable set. Under the Gortex rule I stopped instead of working around it. This review rests on diff.txt and SPEC.md only. It is NOT a clean result: the caller-set hunt (2) and the gate comparison (1) did not run."
  }
}
