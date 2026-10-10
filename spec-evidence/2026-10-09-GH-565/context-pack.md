{
  "likely_touched": {
    "source": "agent",
    "entries": [
      {"path": "src/harnessed/launchscript.py", "why": "Story requires extending parse_script_name to handle the harnessed- prefix on global launcher names and the acp backend, and writing global launchers into ~/.local/bin."},
      {"path": "src/harnessed/launcher.py", "why": "Contains _persist_this_launch, install, uninstall_stack, host-run and container-run commands — all must write/remove global launchers and change when local scripts are written."},
      {"path": "src/harnessed/aoe.py", "why": "Contains _is_launcher_script, _is_ours, and _replays_stack which must be updated to parse stack attribution from the new global-launcher name format instead of --stack flags."},
      {"path": "src/harnessed/attachcmd.py", "why": "Defines _ACP_HARNESSES used by AC-1 and AC-5 to decide whether an ACP global launcher is written."},
      {"path": "src/harnessed/paths.py", "why": "Will need a function or constant for the ~/.local/bin path where global launchers are written."},
      {"path": "tests/test_launchscript.py", "why": "Unit tests for parse_script_name and related script-name logic must cover the new harnessed- prefix and acp backend."},
      {"path": "tests/test_aoe.py", "why": "Tests for _is_launcher_script, _replays_stack, and _is_ours must cover the new global-name row format and backward-compat with old --stack rows."},
      {"path": "tests/test_launcher_install.py", "why": "Tests for harnessed install must assert that global launchers are written to ~/.local/bin and no shim is written."},
      {"path": "tests/test_launcher_build.py", "why": "Tests for harnessed build must assert global launchers are written on build."}
    ]
  },
  "boundaries": {
    "source": "agent",
    "entries": [
      {"module": "src/harnessed/", "holds": "Host Python CLI implementing the harnessed tool: launcher commands, aoe row management, script-name parsing, and path utilities."},
      {"module": "tests/", "holds": "Unit and integration tests covering launcher commands, aoe row recognition/repair, launchscript name parsing, and install/uninstall behavior."}
    ]
  }
}
