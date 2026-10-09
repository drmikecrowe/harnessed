{
  "likely_touched": {
    "source": "agent",
    "entries": [
      {"path": "src/harnessed/launcher.py", "why": "Contains the `container-acp` command implementation (alias of `container-run`) that must be modified to answer `initialize` immediately as a proxy and defer pod start to `session/new` using `cwd` from that request."},
      {"path": "src/harnessed/attachcmd.py", "why": "Defines `_ACP_HARNESSES` and `_acp_attach_cmd`; the proxy's per-harness hard-coded `initialize` capabilities must be anchored here or alongside it."},
      {"path": "src/harnessed/console.py", "why": "Contains `set_acp_mode`, `acp_stdout`, and `restore_acp_stdout` helpers that gate stdout routing for the ACP channel; the proxy mode will extend or modify this gating."},
      {"path": "src/harnessed/paths.py", "why": "Provides `container_project_path` (referenced in the story at emit.py:955) which derives the container-side project path from a host path resolved from `session/new` `cwd`."},
      {"path": "src/harnessed/emit.py", "why": "Uses `paths.container_project_path` at line 955 to write the agent's cwd into the MCP config; the proxy must pass the `cwd`-derived project path through here when starting the pod on `session/new`."},
      {"path": "tools/acp-smoke.py", "why": "AC-3 requires this script passes for both `--harness omp` and `--harness claude` when container-acp starts outside the project; it will need updating to send `cwd` in `session/new` and to work without a project path argument."}
    ]
  },
  "boundaries": {
    "source": "agent",
    "entries": [
      {"module": "src/harnessed/", "holds": "The host-side Python CLI package: launcher commands, path resolution, attach-command derivation, ACP stdout routing, and all pod/container orchestration logic."},
      {"module": "tools/", "holds": "Developer and CI scripts that exercise the CLI end-to-end, including the ACP smoke test that serves as the acceptance-criteria harness for this Story."}
    ]
  }
}
