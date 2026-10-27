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
