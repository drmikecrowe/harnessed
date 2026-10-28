# SPEC — Integrations: one pattern for aoe, Zed, Atlas and VS Code, run with --register-<name>-only

## Summary
What it achieves: a user registers a stack with an external tool (aoe, Zed, Atlas, VS Code) by passing `--register-<name>-only` to the stack's global launcher. Each tool is one integration: an executable file `catalog/integrations/<name>/register`, in the repo catalog or in the user overlay `~/.config/harnessed/catalog/integrations/<name>/register`. A user adds or overrides one there, and no file under `src/harnessed/` changes. That rule governs integrations added after this change; this change itself adds the one-time runner and editor to `src/harnessed/`.

Why: today aoe is the only tool, its code is fixed inside `src/harnessed/`, and every normal launch writes an aoe row and a local launcher in the background whether the user wanted them or not. Zed, Atlas and VS Code entries are written by hand.

What changes: the launcher CLI reads one `--register-<name>-only` flag on the four global verbs (`host-run`, `container-run`, `host-acp`, `container-acp`). The flag builds the stack when its profile is missing or stale, runs the integration, and exits without starting the agent. A normal launch no longer writes an aoe row or a local launcher. The aoe code moves behind a `catalog/integrations/aoe/register` file. Three new integrations write the Zed, Atlas and VS Code config files through a new comment-keeping JSON editor. `--create-aoe-only` is removed. `host-run` accepts the argument shape the VS Code Claude Code extension uses for its process wrapper.

The criteria in plain words:
- AC-1: `--register-aoe-only` writes exactly one aoe row for the project, also on a second run, and keeps or repairs a row made before this change. With no aoe, it fails and writes nothing.
- AC-2: `--register-zed-only` adds or updates one Zed `agent_servers` entry that runs the stack's ACP launcher, and changes no other byte of the file. Invalid JSON is refused and the file is left as it was.
- AC-3: `--register-atlas-only` does the same for the Atlas `installed.json`, keeps other entries, and creates a missing file.
- AC-4: `--register-vscode-only` sets the VS Code `claudeCode.claudeProcessWrapper` setting to the stack's claude launcher, which then runs the extension's claude through the stack. A second stack replaces the value. A non-claude harness is refused.
- AC-5: an integration in the overlay runs, and it wins over a repo integration of the same name. An unknown name lists the available ones and fails.
- AC-6: a launch with no register flag writes no aoe row and no editor entry. `harnessed rm` still removes aoe rows.
- AC-7: a missing or stale profile is built before the integration runs. A current profile is not rebuilt. A failed build runs no integration.

What must not change: launcher names, the global launchers written on every launch, `harnessed rm` removing aoe rows, `harnessed build` running no integration, nothing host-local in `catalog/`, no credential value passed by harnessed to an integration, and no partly written config file.

How each criterion is proven: pytest tests for the flag parser, the lookup, the build-first rule, each integration against a temporary `HOME`, and property tests for the JSON editor. The live CI jobs run, because `launcher.py` is a live trigger. The user confirms the Zed panel, the Atlas list and the VS Code panel by hand, since no test can drive those apps.

Open decisions: none. Ruled by mcrowe on 2026-10-27: `main` rewrites the VS Code wrapper argv; `--create-aoe-only` is removed; the JSON editor is a standard-library module.

## Orientation
- Change: integrations as executable catalog entries, run by `--register-<name>-only` on every global launcher; aoe moves onto the pattern and stops registering automatically.
- Why: registration with external tools is hard-coded for aoe, automatic on every launch, and manual for Zed, Atlas and VS Code.
- Touches: `src/harnessed/launcher.py`, `src/harnessed/paths.py`, new `src/harnessed/integrations.py` and `src/harnessed/jsonc.py`, new `catalog/integrations/{aoe,zed,atlas,vscode}/register`, the agent-of-empires recipe skill, `ARCHITECTURE.md`, tests.
- Decide: the VS Code wrapper argv (S4.4), `--create-aoe-only` removal (S1.8), the JSON editor (S2, S3, S4).
- Decided: Decide 1 A, `main` rewrites the wrapper argv, governs S4.4; Decide 2 A, `--create-aoe-only` is removed, governs S1.8; Decide 3 A, a standard-library `jsonc.py`, governs S2, S3, S4 and Touches (mcrowe, 2026-10-27).

- Tier: 3 — a hand-rolled parser edits user config files, so a defect can destroy a user's file.
- Issue: GH-569
- Isolation: worktree — `GH-569-plugin-support`; `main` takes no commits.

## The integration contract
- An integration is the directory `integrations/<name>/` in a catalog root that holds an executable regular file `register`. The roots are `paths.catalog_roots()`, in order: the user overlay first, then the repo catalog. The first root that holds `integrations/<name>/register` wins.
- harnessed runs `register` with no arguments, with the cwd set to the project path, and with the parent environment plus these variables, each a name or a path:
  - `HARNESSED_INTEGRATION` — `<name>`
  - `HARNESSED_HARNESS`, `HARNESSED_STACK`, `HARNESSED_BACKEND` (`host` or `container`), `HARNESSED_VERB` (the global verb)
  - `HARNESSED_LAUNCHER` — the absolute path of the global launcher for this verb, `~/.local/bin/harnessed-[acp-]<harness>-<stack>-<backend>`
  - `HARNESSED_RUN_LAUNCHER` — the `host-run`/`container-run` launcher of the same backend
  - `HARNESSED_ACP_LAUNCHER` — the ACP launcher of the same backend, or empty when the harness has no ACP mode
  - `HARNESSED_PROJECT` — the absolute project path
  - `HARNESSED_PYTHON` — the interpreter that runs harnessed, so a script can call `"$HARNESSED_PYTHON" -m harnessed.jsonc` or `-m harnessed`
  - `HARNESSED_NO_STRICT_MCP`, `HARNESSED_AOE_GROUP`, `HARNESSED_AOE_TITLE`, `HARNESSED_AOE_MANAGED_WORKTREE` — set only when the launch was given `--no-strict-mcp-config`, `--aoe-group`, `--aoe-title` or `--aoe-managed-worktree`
- harnessed passes the integration's stdout and stderr through and exits with its exit status.
- An integration may hold a `requires` file beside `register`: one requirement per line, `harness <name>...`, `backend host|container` or `acp`, `#` starting a comment. harnessed checks it after the lookup and before any build; a run it rules out exits 1 with the reason and writes nothing, and a line it cannot read exits 2 (Revision 4).
- An entry key for Zed and Atlas is `harnessed <harness> (<stack>)` for the host backend and `harnessed <harness> (<stack>, container)` for the container backend.

## Scenarios
Paths below use `$HOME` for the user's home, and `L` for `$HOME/.local/bin`. "Stack S" is `gortex-ghissues` and "harness H" is `claude` unless a scenario names another.

### S1. aoe (AC-1)
- S1.1 Given aoe on PATH and no harnessed row for project P, when `L/harnessed-claude-gortex-ghissues-host --register-aoe-only` runs in P, then `aoe list -p harnessed` holds one row with path P and command `./claude-gortex-ghissues-host --`, the file `P/claude-gortex-ghissues-host` exists and execs `harnessed-claude-gortex-ghissues-host`, claude is not started, and the exit status is 0.
- S1.2 (boundary) Given the state after S1.1, when the same command runs again, then the row count for P is still 1.
- S1.3 (boundary) Given a row created before this change by `--create-aoe-only` whose command is already `./claude-gortex-ghissues-host --` with path P, when S1.1's command runs, then that row is recognised and kept unchanged as the one row, no row is added, and the exit status is 0: a row that already replays the launcher needs no repair.
- S1.4 (boundary) Given a row created before this change that is drifted (the derived title and path P, but a command in an older form such as `harnessed host-run claude P --stack gortex-ghissues --`, or one that runs another stack), when S1.1's command runs, then the repair `aoe.sync_session` does today runs: the drifted row is renamed `<title> (stale <id>)` and one new row with S1.1's command is added, so one row replays the launcher. This rename-and-add is the repair AC-1 names; the drifted row is not edited in place, and the renamed row no longer counts as a row for this launcher.
- S1.5 (negative) Given no `aoe` on PATH, when S1.1's command runs, then stderr names Agent of Empires as not installed, the exit status is 1, and no row and no local launcher are written.
- S1.6 (boundary) Given the agent-of-empires skill's call, when `--register-aoe-only --aoe-group G --aoe-title T --aoe-managed-worktree` runs, then the row has group G and title T, and is written in the foreground.
- S1.7 (negative) Given an ACP launcher, when `L/harnessed-acp-claude-gortex-ghissues-host --register-aoe-only` runs, then stderr says aoe replays a terminal launcher and names `harnessed-claude-gortex-ghissues-host`, the exit status is 1, and nothing is written.
- S1.8 (negative) Given `--create-aoe-only` is removed (ruled by mcrowe, 2026-10-27), when `--create-aoe-only` is passed, then typer rejects it as an unknown option with exit status 2.

### S2. Zed (AC-2)
- S2.1 Given `$HOME/.config/zed/settings.json` with an `agent_servers` object that lacks the entry, when `L/harnessed-claude-gortex-ghissues-host --register-zed-only` runs, then `agent_servers["harnessed claude (gortex-ghissues)"]` is `{"type": "custom", "command": "<L>/harnessed-acp-claude-gortex-ghissues-host", "args": [], "env": {}}`, and the exit status is 0.
- S2.2 (boundary) Given the state after S2.1, when the command runs again, then the file is byte-identical to the file after S2.1.
- S2.3 (boundary) Given a file with `//` and `/* */` comments, a trailing comma, and other members, when S2.1's command runs, then a text diff of the file before and after shows changes only inside the entry's lines.
- S2.4 (boundary) Given an existing entry with the same key that holds `default_config_options` and a different `command`, when S2.1's command runs, then `type` and `command` take S2.1's values and `default_config_options`, `args` and `env` keep their bytes.
- S2.5 (boundary) Given no settings file, or a file with no `agent_servers`, when S2.1's command runs, then the file holds S2.1's entry inside an `agent_servers` object, and any members that were there keep their bytes.
- S2.6 (negative) Given a settings file that is not valid JSON with comments (for example a missing `}`), when S2.1's command runs, then stderr names the file and the line of the error, the exit status is 1, and the file is byte-identical.
- S2.7 (negative) Given a harness with no ACP mode, when its launcher runs `--register-zed-only`, then stderr says Zed needs an ACP harness and names the ACP harnesses, the exit status is 1, and nothing is written.
- S2.8 (boundary) Given the container launcher `L/harnessed-claude-gortex-ghissues-container`, when it runs `--register-zed-only`, then the entry key is `harnessed claude (gortex-ghissues, container)` and its command is `<L>/harnessed-acp-claude-gortex-ghissues-container`, and a host entry is left as it was.

### S3. Atlas (AC-3)
- S3.1 Given `$HOME/.local/share/dev.atlas.ide/external-agents/installed.json` as a JSON object without the entry, when `--register-atlas-only` runs on S2.1's launcher, then the object holds `"harnessed claude (gortex-ghissues)": {"type": "custom", "command": "<L>/harnessed-acp-claude-gortex-ghissues-host", "args": []}`, and the exit status is 0.
- S3.2 (boundary) Given the file holds two other entries, when S3.1's command runs, then both other entries keep their bytes.
- S3.3 (boundary) Given no file and no `external-agents` directory, when S3.1's command runs, then the directory and the file are created and the file holds only S3.1's entry.
- S3.4 (negative) Given a file that is not valid JSON, when S3.1's command runs, then stderr names the file, the exit status is 1, and the file is byte-identical.
- S3.5 (negative) Given a harness with no ACP mode, when its launcher runs `--register-atlas-only`, then the result is S2.7's, naming Atlas.

### S4. VS Code (AC-4)
- S4.1 Given `$HOME/.config/Code/User/settings.json`, when `L/harnessed-claude-gortex-ghissues-host --register-vscode-only` runs, then the file holds `"claudeCode.claudeProcessWrapper": "<L>/harnessed-claude-gortex-ghissues-host"` at the top level, and the exit status is 0.
- S4.2 (boundary) Given the state after S4.1, when `L/harnessed-claude-superpowers-host --register-vscode-only` runs, then the setting holds only `<L>/harnessed-claude-superpowers-host` and a text diff shows changes only on that member's line.
- S4.3 (negative) Given `L/harnessed-omp-gortex-ghissues-host --register-vscode-only`, then stderr says the vscode integration supports claude only, the exit status is 1, and the file is byte-identical.
- S4.4 Given the extension's wrapper call (the shape read from the Claude Code extension 2.1.296's `extension.js`, which sets the wrapper as the executable and the bundled claude as its first argument), `L/harnessed-claude-gortex-ghissues-host /x/claude --output-format stream-json --input-format stream-json --verbose`, where `/x/claude` is an executable file named `claude`, when it runs, then `host-run` starts the stack's claude in the cwd with exactly the arguments after `/x/claude` as passthrough, and `/x/claude` is not run (the argv rule in `main`, ruled by mcrowe, 2026-10-27).
- S4.5 (negative) Given a settings file that is not valid JSON with comments, when S4.1's command runs, then the result is S2.6's.
- S4.6 (boundary) Given the state after S4.1, when the user opens the Claude Code panel in VS Code and sends a prompt, then the session runs through the stack: the user confirms this by hand.
- S4.7 (negative) Given the container launcher `L/harnessed-claude-gortex-ghissues-container --register-vscode-only`, then stderr says the vscode integration supports the host backend only, the exit status is 1, and the file is byte-identical.

### S5. Lookup and the runner (AC-5)
- S5.1 Given an overlay `integrations/zellij/register` that writes its `HARNESSED_*` variables to a file, when `--register-zellij-only` runs on S2.1's launcher, then the file holds `HARNESSED_INTEGRATION=zellij`, `HARNESSED_HARNESS=claude`, `HARNESSED_STACK=gortex-ghissues`, `HARNESSED_BACKEND=host`, `HARNESSED_LAUNCHER=<L>/harnessed-claude-gortex-ghissues-host`, and the cwd was the project path.
- S5.2 (boundary) Given `integrations/zellij/register` in both the overlay and the repo catalog, each writing a different marker, when S5.1's command runs, then only the overlay marker exists.
- S5.3 (negative) Given no integration named `nosuch`, when `--register-nosuch-only` runs, then stderr lists the available integration names, sorted, from every root, the exit status is 2, and no build runs.
- S5.4 (negative) Given `integrations/zellij/register` that is not executable, when S5.1's command runs, then stderr names the file and says it is not executable, and the exit status is 2.
- S5.5 (boundary) Given an integration that exits 3, when it runs, then the launcher exits 3.
- S5.6 (negative) Given two register flags on one command, when it runs, then stderr says only one is allowed, the exit status is 2, and nothing runs.
- S5.7 (boundary) Given a register flag after a standalone `--`, when the launcher runs, then the flag is passthrough for the harness and no integration runs.
- S5.8 Given S5.1's command run with a parent environment E, then the integration's environment equals E plus exactly the contract's variables (no other name is added and no name in E is changed), and each added value is a name, a path, `0`/`1`, or an `--aoe-*` value the user typed; harnessed reads no credential store to build them.

### S6. No automatic registration (AC-6)
- S6.1 Given a project with no aoe row, when `L/harnessed-claude-gortex-ghissues-host` runs with no register flag, then claude starts, `aoe.sync_session` is not called, no local launcher is written, and the Zed, Atlas and VS Code files are untouched.
- S6.2 (boundary) Given an aoe row for stack S, when `harnessed rm S` runs, then `aoe.forget_stack` removes that row, as today.
- S6.3 (negative) Given no `integrations/aoe/` in any root, when `--register-aoe-only` runs, then the result is S5.3's.
- S6.4 (boundary) Given a launch with no register flag, then the global launchers are written as today.

### S7. Build first (AC-7)
- S7.1 Given no profile for stack S and harness H, when any `--register-<name>-only` runs on S's launcher for a known name, then the stack is built before the integration: `_build_stack(rt, S, H)` for a container verb, and for a host verb the in-process assembly `host-run` does, which needs no container runtime (Revision 4).
- S7.2 (boundary) Given a profile whose `.build-stamp` does not match `staleness.compute_stamp` (the check `staleness.check_profile_fresh` makes), when S7.1's command runs, then the stack is built before the integration.
- S7.3 (boundary) Given a current profile, when S7.1's command runs, then no build runs.
- S7.4 (negative) Given a build that fails, when S7.1's command runs, then the integration does not run, nothing is written, stderr holds the build's error, and the exit status is 1.
- S7.5 Given S7.1 then S2.1 have run, when an ACP `initialize` request is written to `L/harnessed-acp-claude-gortex-ghissues-host`, then the reply holds `"result"`.

## Must NOT
- A launch with no register flag changes only in that it writes no aoe row and no local launcher; every other existing launch test passes unchanged.
- Launcher names stay `harnessed-[acp-]<harness>-<stack>-<backend>` (GH-565).
- Global launchers are still written on every launch, and `harnessed uninstall` still removes them.
- `harnessed rm` still removes the stack's aoe rows.
- `harnessed build` runs no integration.
- No integration file holds a host-local path or value: `catalog/` ships in the wheel.
- harnessed passes no credential value to an integration.
- A config file that fails to parse is never written, and a write replaces the file whole (write a temporary file in the same directory, then rename), so a crash leaves the old file.
- No new runtime dependency, and no `npm` or `npx`.
- Under an ACP verb, a register run writes nothing to stdout before it exits.

## Failure model
- A JSON-with-comments edit corrupts a user's settings file — property tests on the editor (parse after edit equals the intended value; bytes outside the edited span unchanged) and mutation testing on `jsonc.py`.
- A crash mid-write truncates a settings file — the temporary-file-and-rename write; a test that the old file survives a failed rename.
- An integration runs against a stale profile and registers a launcher that cannot start — S7 tests.
- A normal launch still mirrors to aoe — S6.1 test that `sync_session` is not called.
- The overlay loses to the repo copy — S5.2 test.
- The flag parser eats a passthrough argument — S5.7 test.
- An ACP launcher prints to stdout before exit — test that stdout is empty under a register run on `host-acp`.

## Touches
- `src/harnessed/launcher.py` — `main` splits one `--register-<name>-only` off argv before typer; `host_run`, `container_run` and `host_acp` call the runner first when it is set; the passive aoe mirror and the local-launcher write leave the normal launch; `--create-aoe-only` is removed; the register sequence (`_own_launcher_or_exit`, `launchscript.write`, `_aoe_register`) moves into a hidden `aoe-register` command that reads the contract's variables; `main` rewrites the VS Code wrapper argv (S4.4).
- `src/harnessed/integrations.py` (new) — find, list, build-first, and run an integration.
- `src/harnessed/jsonc.py` (new, standard library only, ruled by mcrowe, 2026-10-27) — parse JSON with comments and trailing commas, set a member by key path as a text edit, write by rename; `python -m harnessed.jsonc set <file> <key>... <json-value>`.
- `src/harnessed/paths.py` — `_KIND_MARKER["integrations"] = "register"`.
- `catalog/integrations/aoe/register` (new, mode 755) — refuses an ACP verb, then `exec "$HARNESSED_PYTHON" -m harnessed aoe-register`.
- `catalog/integrations/zed/register`, `catalog/integrations/atlas/register`, `catalog/integrations/vscode/register` (new, mode 755) — check the harness, then call `harnessed.jsonc`.
- `catalog/recipes/agent-of-empires/skills/agent-of-empires/scripts/aoe-sessions` and `catalog/recipes/agent-of-empires/recipe.yaml` — `--create-aoe-only` becomes `--register-aoe-only`.
- `ARCHITECTURE.md` — define *integration*; replace the `--create-aoe-only` text at the skipped-stacks table and the aoe section.
- `tests/test_integrations.py`, `tests/test_jsonc.py` (new); `tests/test_aoe.py`, `tests/test_host_run_recipes.py`, `tests/test_adhoc_launch_is_not_persisted.py`, `tests/test_stale_profile_prompt.py`, `tests/test_launch_host.py` — follow the flag and the removed mirror.

## Documentation
- `ARCHITECTURE.md` — the integration vocabulary and the register flag.
- The wiki pages for Zed, Atlas and VS Code (README.md:158, :194 link them) are a separate delivery in `main/docs/`; this PR does not carry them.

## Known limits
- In VS Code, `host-run` runs the stack's own claude, not the extension's bundled binary, so the two versions can differ. The vscode integration refuses the container backend (S4.7), because the wrapper path under `container-run` is not checked.
- The JSON editor reads JSON with `//` and `/* */` comments and trailing commas. It refuses JSON5 forms (unquoted keys, single quotes) as invalid and leaves the file as it was.
- Only aoe has an unregister path (`harnessed rm`). Zed, Atlas and VS Code entries stay until the user removes them.
- The integration inherits the user's own environment; harnessed adds only names and paths to it.
- The shellcheck layer reads tracked `*.sh` files only, so the `register` scripts are checked by hand in EVIDENCE.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1.1-S7.4 and every existing test | `tools/run-tests.sh` passes; count ≥ baseline + the new tests |
| property | `jsonc.py` edit and parse | hypothesis tests pass |
| mutation | `jsonc.py` and `integrations.py` | no surviving mutant left unexplained in EVIDENCE |
| coverage | branch coverage of `src` | ≥ 80% (`--cov-fail-under=80`) |
| types | pyright over the dev environment | 0 errors |
| lint | ruff over `src tests tools` | 0 findings |
| shellcheck | every tracked `*.sh`, plus the four `register` scripts by hand | 0 findings |
| secrets | gitleaks over the history | 0 leaks |
| live | `live` and `live-docker` on the PR, since `launcher.py` and `paths.py` are live triggers | both jobs pass |
| manual | S4.6, S7.5, and the Zed panel and Atlas list showing the entry | the user confirms each |
