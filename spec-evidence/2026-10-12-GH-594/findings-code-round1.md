{
  "clean_claims": [
    "src/harnessed/jsonmerge.py merge_claude_json and seed_claude_project, as shown in diff.txt: S1.1 to S1.11 hold on reading, and the inputs are copied, not mutated.",
    "tests/test_claude_json_merge.py: the property test S1.12 matches the SPEC."
  ],
  "finding": [
    {
      "file": "src/harnessed/jsonmerge.py",
      "line": 183,
      "severity": "advisory",
      "rule": "AC-5 / AC-4",
      "defect": "The live file is the unconditional base, and the diff gives no migration for stacks that already hold the old wholesale copy of the user's ~/.claude.json. The old code copied that file whole, and src/harnessed/hosthome.py now keeps .claude.json across rebuilds via keep=(\".claude.json\",). Nothing removes the user's old `projects` or `mcpServers` from a kept file.",
      "trigger": "A host stack launched before this change, then launched again after it. Its .claude.json already holds the user's `mcpServers` and `projects`, such as '/secret'.",
      "consequence": "The host's global `mcpServers` and other projects stay in the stack file forever, which contradicts AC-5 for every existing host stack. `--strict-mcp-config` stops them loading, so the leak is of data, not behaviour. S1.9 scrubs only the identity pair, and only when it equals the host's exactly. No test covers this upgrade state."
    }
  ],
  "hunch": [
    {
      "file": "src/harnessed/launcher.py",
      "line": 3363,
      "rule": "none",
      "defect": "The `elif harness == \"claude\":` that seeds project trust attaches to an `if` the diff does not show. I could not confirm the condition is exactly `project_only`, or that `project_only` is True only for host-acp. If it is also True for a non-acp host run where the stack home was already built, a seed with no onboarding or identity could run.",
      "consequence": "Trust keys could be written to a home that was never materialized, or to a home an agent is running on. The `if not target.is_file()` guard limits the damage."
    },
    {
      "file": "src/harnessed/hosthome.py",
      "line": 197,
      "rule": "none",
      "defect": "I could not open `_clear_host_home_except_runtime` to confirm it accepts a `keep=` argument and keeps exactly that name. I also could not open `_host_fresh_wipe` or `_scrub_host_home` to see whether they still delete .claude.json.",
      "consequence": "If `keep` is unsupported there is a TypeError on every host rebuild, but the S3.5 test would catch that. If the wipe paths delete the file, answers are lost on a fresh wipe. That may be intended."
    },
    {
      "file": "src/harnessed/hosthome.py",
      "line": 496,
      "rule": "none",
      "defect": "`_seed_host_claude_json` does an unlocked read-modify-write of the whole file with `os.replace` while another session can be using the same stack home. The stack home is not per project. A second host-run on the same stack in another project makes `merge_claude_json` rebuild from the file it just read, so a concurrent in-agent write can be lost.",
      "consequence": "A lost answer, or a clobbered seed. This is the same window the SPEC's Known limits admit for host-acp. I did not check whether the home lock covers it."
    },
    {
      "file": "src/harnessed/mounts.py",
      "line": 188,
      "rule": "none",
      "defect": "The container stub is written in place with `write_text`, not atomically, and the stub path is per instance. A relaunch while a container of the same instance is running, or a crash mid-write, leaves a truncated file.",
      "consequence": "`read_json_or_empty` then treats it as `{}`, so every in-stack answer is silently lost. A bind mount needs the same inode, so an atomic replace is not a drop-in fix."
    }
  ],
  "coverage": {
    "calls_used": "5/10",
    "hunts_not_reached": [
      "1 (gate commands vs layer manifest: the manifest, test.yml and lint.yml were not opened)",
      "2 (callers of the changed functions outside the diff, e.g. other HostBackend constructors or other users of _share_host_claude_state)",
      "6",
      "7",
      "8 (no EVIDENCE.md in the diff)",
      "9 (the keep= parameter was not confirmed)",
      "10"
    ],
    "sites_not_opened": [
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/hosthome.py:_clear_host_home_except_runtime",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/hosthome.py:_host_fresh_wipe",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/src/harnessed/launcher.py:_launch_host (the project_only condition near line 3363)",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/tools/gauntlet-layers.json",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/test.yml",
      "/home/mcrowe/Programming/Personal/harnessed/gh-594-merge-claude-json/.github/workflows/lint.yml"
    ]
  }
}
