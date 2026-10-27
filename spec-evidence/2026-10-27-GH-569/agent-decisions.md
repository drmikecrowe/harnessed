# Agent decisions: Integrations: one pattern for aoe, Zed, Atlas and VS Code, run with --register-<name>-only

### A1. An integration is a directory with an executable file named `register`
- Other option: any single executable file in the directory, whatever its name.
- Why: a fixed marker name fits `_KIND_MARKER` and lets `find_in_catalog`/`list_catalog` serve the new kind unchanged.
- Command: plan

### A2. The container backend's Zed and Atlas key adds `, container`
- Other option: one key per harness and stack, so registering the container launcher replaces the host entry.
- Why: AC-2 and AC-3 name only the host key; a separate key keeps both entries instead of one silently replacing the other.
- Command: plan

### A3. The aoe integration refuses an ACP launcher
- Other option: map an ACP verb to the run verb of the same backend and register that.
- Why: an aoe row replays a terminal launcher, so a row from an ACP launcher would be a guess; refusing is one check and names the right launcher.
- Command: plan

### A4. Zed updates only `type` and `command` in an existing entry
- Other option: replace the whole entry value.
- Why: a user's entry can hold `default_config_options` (fact 13); replacing it would delete the user's settings.
- Command: plan

### A5. The launch's aoe options reach the aoe integration as `HARNESSED_AOE_*` variables
- Other option: pass the launch's remaining argv to `register` as arguments.
- Why: typer has already parsed those options; variables keep the integration's interface to names and values, the same as the other variables.
- Command: plan

### A6. One register flag per command
- Other option: run several integrations in order from one command.
- Why: the story names one flag per run, and one exit status per integration stays clear.
- Command: plan

### A7. The VS Code argv rule reads only the first positional token after the options
- Other option: drop the first absolute path to an executable `claude` found anywhere in argv.
- Why: the wrapper call puts it right after `--stack S`; reading one position cannot misread an option value elsewhere.
- Command: build

### A8. The Zed, VS Code and Atlas paths honour `XDG_CONFIG_HOME` and `XDG_DATA_HOME`
- Other option: the fixed `$HOME/.config` and `$HOME/.local/share` paths the scenarios name.
- Why: Zed, Electron and Tauri read those variables on Linux, and with them unset the paths are the scenarios' paths.
- Command: build

### A9. An optional contract name the parent set is removed unless this launch was given its flag
- Other option: pass the parent's value through unchanged.
- Why: a value an outer launch left in the environment would read as this launch's `--aoe-group`.
- Command: build

### A10. The JSON editor inserts a new member first in its object, at the start of its own line
- Other option: append it after the last member.
- Why: appending adds a comma to the line above, which S2.3 forbids; inserting first changes no existing line.
- Command: build

### A11. Zed and Atlas write with `setdefault` on the entry, then `set` on `type` and `command`
- Other option: one `merge` operation that writes the file once.
- Why: three single-value edits reuse one primitive; each write is atomic and a repeat run writes nothing.
- Command: build

### A12. A normal launch still passes the harness `--name <row title>` when aoe is usable
- Other option: drop the `--name` too, since a launch writes no row.
- Why: the Must NOT keeps every other launch behaviour; a row registered by `--register-aoe-only` still carries that title.
- Command: build

### A13. The JSON editor writes through a symlink to its target
- Other option: replace the link with a regular file, as a plain rename does.
- Why: dotfile managers link settings files, and replacing the link would silently detach the user's managed copy.
- Command: build

### A14. The local launcher `aoe-register` writes carries no `# as typed:` line
- Other option: pass the typed command line to `aoe-register` in another variable.
- Why: the line is display only, and a variable outside the contract would widen it for one comment.
- Command: build

### A15. The vscode integration registers `HARNESSED_RUN_LAUNCHER`, not `HARNESSED_LAUNCHER`
- Other option: register `HARNESSED_LAUNCHER`, the launcher the flag was given to.
- Why: from an ACP launcher that would set the wrapper to an ACP agent, which the extension cannot run.
- Command: build

### A16. A register run skips the claude imports prompt a `host-run` launch asks
- Other option: ask it, as a launch does.
- Why: no agent starts, and the agent-of-empires skill runs the flag from a script with no one to answer.
- Command: build

### A17. Only the aoe integration refuses a foreign file at the global launcher's name
- Other option: the runner refuses every integration when its own global launcher was not written.
- Why: aoe already refused it (S1.13); the editors name the launcher path, which the user may own on purpose.
- Command: build
