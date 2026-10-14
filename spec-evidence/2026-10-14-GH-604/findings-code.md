{
  "clean_claims": [
    "src/harnessed/launcher.py:4913-5049: the three call sites of _acp_adapter_install_cmd (4990, 4998, 5016) all pass the new owner argument. Nothing outside launcher.py calls it.",
    "launcher.py:5031-5049: the typed 'c' path sets cmd to bash, so the recheck runs, as Decide 2 A requires. A failed install returns before the recheck. The mise command skips it.",
    "paths.xdg_data_home exists (paths.py:308), so _mise_data_dir resolves.",
    "host-acp stdout stays empty: the new pnpm probe captures its output and the diagnostics go to _err."
  ],
  "finding": [],
  "hunch": [
    {
      "file": "src/harnessed/launcher.py",
      "line": 4913,
      "rule": "none",
      "defect": "Mise locations are recognised only under $MISE_DATA_DIR/{installs,shims}. A user who sets MISE_SHIMS_DIR or MISE_INSTALL_DIR elsewhere, or whose MISE_DATA_DIR is relative or starts with ~, is classed 'other' and gets pnpm add -g. Path.is_relative_to compares paths as text.",
      "consequence": "For those layouts the original bug returns: the pnpm install is shadowed by the mise copy and the offer repeats. S5.2 would report the shadowing."
    },
    {
      "file": "src/harnessed/launcher.py",
      "line": 4998,
      "rule": "none",
      "defect": "_acp_adapter_owner can run `pnpm bin -g` (10 s timeout) inside _require_acp_adapter, on the host-acp startup path where an editor is waiting on the process. The SPEC lists this under Known limits.",
      "consequence": "A hung pnpm delays the ACP handshake by up to 10 s on each launch."
    }
  ],
  "coverage": {
    "calls_used": "4/10",
    "hunts_not_reached": [
      "1 (merge-gate argument comparison: the workflows and tools/gauntlet-layers.json were not opened)",
      "8 (no EVIDENCE report in the diff)",
      "9 (the real layout of mise's npm backend installs dir was not verified)"
    ],
    "sites_not_opened": [
      "tests/test_host_acp.py: the host fixture and its path_prefix handling",
      "/home/mcrowe/Programming/Personal/harnessed/worktrees/GH-604/.github/workflows/test.yml, lint.yml, live.yml"
    ]
  }
}
