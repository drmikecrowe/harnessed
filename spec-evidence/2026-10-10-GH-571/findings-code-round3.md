{
  "clean_claims": [
    "diff-r3.txt hunks for tests/test_host_acp.py and tests/test_acp_smoke.py: read, no defect found in the tests as written"
  ],
  "finding": [],
  "hunch": [
    {
      "file": "src/harnessed/launcher.py",
      "line": 3152,
      "rule": "none",
      "defect": "The diff gates only some per-stack steps behind `project_only`. The code between the entry validation and the line-3188 launcher block was not in the diff and I could not open it: the assemble guard, the 'Same mirror as the container path' record, the `_host_launch_plan` setup, and whatever sits above the `_write_global_launchers` call.",
      "consequence": "Any ungated state write there (the mirror record, secrets resolution, a build stamp) would run in project-only mode against the stack's host home while an agent is running. This is the exact class you briefed me on."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 3678,
      "rule": "none",
      "defect": "The deleted `project_setup` body checked that the harness is a host harness, that the project path is a directory (`is_dir`), and that the stack exists. I could not confirm `_launch_host` makes the same checks for a nonexistent `path`.",
      "consequence": "If `_launch_host` does not check the path, project-setup would run recipe scripts with cwd or env pointing at a missing folder. The failure would come late or be unclear instead of the clean exit 1."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 3076,
      "rule": "none",
      "defect": "`out` is a BufferedWriter that is no longer closed, and the process ends with `os._exit`, which does not flush Python buffers. Closing used to flush it.",
      "consequence": "If acprelay's `emit` does not flush after each write, the last replies (such as the setup-failed error) are lost at exit. I did not open acprelay.emit to check."
    },
    {
      "file": "src/harnessed/acprelay.py",
      "line": 92,
      "rule": "none",
      "defect": "`_stop` returns as soon as `setup.wait` reports the group leader exited after SIGTERM, without sending SIGKILL to the rest of the group.",
      "consequence": "A setup child that ignores TERM, such as a service container wrapper, survives the relay when the leader exits on TERM. The 'stopped by process group' claim holds only for children that honour TERM."
    },
    {
      "file": "tools/acp-smoke.py",
      "line": 118,
      "rule": "none",
      "defect": "`_cwd_matches` splits the reply on whitespace and quotes, so a folder path containing spaces can never match.",
      "consequence": "The smoke check fails falsely for a project under a path with a space. Temp dirs are space-free, so tests will not show it."
    }
  ],
  "coverage": {
    "calls_used": "3/10",
    "hunts_not_reached": [
      "1 (merge-gate argument comparison)",
      "2 (call sites of _launch_host, _intercept and run outside the diff)",
      "3 (full enumeration of per-stack steps against project_only)",
      "6",
      "7",
      "8",
      "9",
      "10"
    ],
    "sites_not_opened": [
      "src/harnessed/launcher.py:3128-3300 (the middle of _launch_host, blocked)",
      "src/harnessed/launcher.py:3319-3330 (merge_settings gating, seen only in the diff)",
      "src/harnessed/launcher.py:3361-3500 (wire_mcp, exec, and what follows the project_only return)",
      "src/harnessed/acprelay.py:run emit and flush",
      "tools/acp-smoke.py:launch_dir definition",
      "tools/gauntlet-layers.json and .github/workflows/*.yml",
      "Reason for the gaps: the Gortex PreToolUse hook blocked Read and Grep on src/harnessed/launcher.py. The Gortex MCP tools are not callable from my toolset. This is a Gortex MCP integration failure; I did not use a shell fallback."
    ]
  }
}
