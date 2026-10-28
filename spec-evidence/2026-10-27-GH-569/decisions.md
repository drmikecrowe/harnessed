# Decisions — Integrations: one pattern for aoe, Zed, Atlas and VS Code, run with --register-<name>-only

## Setup plan
- Isolation: worktree `GH-569-plugin-support` (branch `GH-569-plugin-support`) — `main` takes no commits (AGENTS.md, Git workflow).
- Git: one signed commit per step of the process; the change in one or more signed commits; PR to `main`.
- New dependencies: none. The JSON editor uses the standard library (`json`, `os`, `tempfile`). `hypothesis` and `mutmut` are already dev extras (pyproject.toml:32, :36).
- New files: `src/harnessed/integrations.py`, `src/harnessed/jsonc.py`, `catalog/integrations/{aoe,zed,atlas,vscode}/register`, `tests/test_integrations.py`, `tests/test_jsonc.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares six layers — tests (`tools/run-tests.sh`), coverage (pytest-cov, 80% floor), types (pyright), lint (ruff on src, tests, tools), shellcheck (tracked `*.sh`), secrets (gitleaks). All six are declared and run. Missing for this change: shellcheck does not reach the extensionless `register` scripts; they are checked by hand. Property (hypothesis) and mutation (mutmut) are declared as dev extras and run for Tier 3.
- Merge gate: `.github/workflows/test.yml`, `.github/workflows/lint.yml`, `live.yml` — pytest → tests; ruff → lint; pyright → types; shellcheck → shellcheck; `live` and `live-docker` run because `src/harnessed/launcher.py` and `src/harnessed/paths.py` are live triggers (AGENTS.md, Tests).

## Facts this SPEC rests on
1. A global launcher is `#!/bin/sh`, the sentinel, and `exec <harnessed> <verb> <harness> --stack <stack> "$@"` — launchscript.py:402-408, read by a research subagent.
2. Backends are `host` and `container`; the global verbs are host-run, container-run, host-acp, container-acp; ACP launchers exist only for `attachcmd._ACP_HARNESSES` — launchscript.py:75-89, :177-183.
3. `main` already splits argv before typer (`_extract_passthrough`, `_extract_acp_cli`) — launcher.py:6648-6690, read directly.
4. `container-acp` and `container-exec` are aliases of `container_run`, `host-exec` of `host_run` — launcher.py `_EXEC_ALIAS`, read directly.
5. A normal launch writes the local launcher and calls `aoe.sync_session(background=True)` when `_persist_this_launch` passes — launcher.py:3222-3247, :4590-4612, :2667-2695, read directly.
6. The aoe row's command is `./<harness>-<stack>-<backend> --`; an existing row is matched by path and launcher-script basename; a drifted row (our title and path, another command) is renamed `<title> (stale <id>)` and replaced — aoe.py:250, :540-597, :691-722.
7. `harnessed rm` calls `aoe.forget_stack` — launcher.py:5412-5432.
8. Stale means `.build-stamp` missing or not equal to `compute_stamp` (harnessed version, stack.yaml bytes, every recipe dir) — staleness.py:13-27, :52, :103-119. `host-run` reassembles on every launch and checks no stamp; `container-run` prompts at a TTY. `_build_stack(rt, stack, harness)` builds one harness — launcher.py:804.
9. `paths.catalog_roots()` puts the overlay first; `find_in_catalog`/`list_catalog` key a kind on `_KIND_MARKER`, which has no `integrations` entry — paths.py:415-540.
10. `catalog/**/*` ships in the wheel, and 100755 files under `catalog/` already rely on the exec bit surviving install — pyproject.toml:150-166, launcher.py:3093-3095.
11. No Zed, Atlas or VS Code registration code exists, and no JSON-with-comments parser is a dependency — rg over src/ and catalog/, pyproject.toml:10-14.
12. The Atlas file is a JSON object keyed by entry name, each value `{"type": "custom", "command": ..., "args": []}` — read from this machine's `installed.json`.
13. Zed `agent_servers` entries are `{"type": "custom", "command": ..., "args": [], "env": {}}`, and a user's entry can hold `default_config_options` — read from this machine's `settings.json`.
14. The VS Code Claude Code extension (2.1.296) spawns the wrapper as `<wrapper> <bundled claude path> <SDK args>`: `pathToClaudeCodeExecutable` is the wrapper and `executableArgs` is the bundled binary — extension.js `mS`, read directly. So the global launcher receives `host-run claude --stack S /x/claude --output-format ...`, and today typer binds `/x/claude` to the project path and rejects the SDK flags. This answers the story's SR-DEFER on AC-4: the wrapper arguments do not work with `host-run` as it stands, hence S4.4 and Decide 1.
15. The agent-of-empires skill calls `--aoe-group G --aoe-title T --create-aoe-only --aoe-managed-worktree` — aoe-sessions:446.
16. The story's SR-DEFER "nothing under `src/harnessed/` changes" holds for adding or overriding an integration once this change lands; this change itself adds the runner and the editor to `src/`, and moves the aoe code behind the hidden `aoe-register` command.

## Intent review
- Accepted: repair of a pre-change row (S1.3, S1.4 now say a matching row is kept and an older-form row is repaired); the container backend under VS Code (new S4.7, Known limits); the credential constraint (S5.8 now compares the child environment with the parent's).
- Declined: cut the extra variables, `aoe-register`, the `jsonc` CLI and S1.7 — the agent-of-empires skill passes `--aoe-group`/`--aoe-title`/`--aoe-managed-worktree` (fact 15), the shipped integrations are scripts that need one entry point each into harnessed, and S1.7 refuses a row that would be a guess (A3).
- Declined: cut S5.4, S5.5, S5.6 and exit status 2 — each pins an edge the runner must decide anyway; 2 is the usage-error status typer already uses, and it is non-zero as the story asks.
- Declined: the extra Zed and Atlas fields — read from the entries Zed and Atlas hold on this machine (facts 12, 13).

## Decide calls

### Decide 1. How does the global claude launcher take the VS Code wrapper argv?
Evidence: fact 14; launcher.py `main` (fact 3).

- A. `main` rewrites the argv of `host-run`/`container-run` for harness `claude`: when the first positional token after the options is an absolute path to an executable file named `claude`, drop it and treat every later token as passthrough. Cost: one argv rule in `main`; a project directory that is itself an executable file named `claude` would be misread, which cannot happen for a directory.
- B. The vscode integration writes a separate wrapper script that inserts `--` and execs the launcher. Cost: a second generated file per stack, and AC-4's literal setting value (the launcher path) is not met.

Default: A. Ruling: A, rewrite argv in main (mcrowe, 2026-10-27).
Changes: S4.4 states the rule; Orientation `Decided:` names it.

### Decide 2. What happens to `--create-aoe-only`?
Evidence: launcher.py:3611, :4437; aoe-sessions:446; ARCHITECTURE.md:318, :366.

- A. Remove it; the skill and the docs move to `--register-aoe-only`. Cost: a user's own script that passes `--create-aoe-only` fails with an unknown-option error.
- B. Keep it as a hidden alias for `--register-aoe-only`. Cost: two names for one act, and the alias stays until someone removes it.

Default: A. Ruling: A, remove it (mcrowe, 2026-10-27).
Changes: S1.8 applies unconditionally; Orientation `Decided:` names it.

### Decide 3. How is the comment-keeping JSON editor built?
Evidence: fact 11; AGENTS.md (pnpm only, pin every download).

- A. A small standard-library module `src/harnessed/jsonc.py`: a tokenizer that records spans, so a set replaces one value's bytes or inserts one member. Cost: a hand-rolled parser (Tier 3: property and mutation tests).
- B. Microsoft's `jsonc-parser` through a pinned `pnpm dlx`. Cost: Node and network at registration time, a new pinned download, and a JS shim between the integration and the library.

Default: A. Ruling: A, stdlib module jsonc.py (mcrowe, 2026-10-27).
Changes: Touches names `src/harnessed/jsonc.py`; Orientation `Decided:` names it.

## Revisions
### Revision 1. Intent review folded in; Decide 1-3 ruled A
S1.3, S1.4, S4.7, S5.8 and Known limits changed from the intent review; the three rulings are written at S4.4, S1.8 and Touches.
### Revision 2. Gate 1a round 1 finding PR-REFERENT applied
The Orientation Decide line pointed the `--create-aoe-only` removal at S1.7; it is S1.8.
### Revision 3. Intent review round 2 folded in
Accepted: the Summary says the no-src rule governs later integrations; S1.4 says rename-and-add is the AC-1 repair; S4.4 cites the extension source for the wrapper argv (fact 14). Declined: ask about Zed `args` and `env` — both are in every Zed entry on this machine (fact 13), and S2.4 keeps an existing entry's values.
### Revision 4. Host verbs assemble in-process; `requires` is checked before any build
Ruled by mcrowe on 2026-10-28, on PR #645: `harnessed-omp-se-ghissues-host --register-vscode-only` ran the full container image build, then refused, because S7.1 named `_build_stack` for every verb and the harness check lived in the `register` script. S7.1 now builds a host verb's profile with the in-process assembly `host-run` does, and the contract adds the `requires` file, so a run an integration rules out builds nothing. The vscode, zed and atlas checks moved from their scripts into `requires`.
### Revision 5. The editor integrations read each app's macOS location
mcrowe asked on 2026-10-28 that the hard-coded paths work on macOS. Checked against each app: Zed's `paths::config_dir()` is `~/.config/zed` on macOS and ignores `XDG_CONFIG_HOME`; VS Code's settings docs give `~/Library/Application Support/Code/User/settings.json`; Atlas's file sits in Tauri's appDataDir, `~/Library/Application Support/<identifier>` on macOS, with the identifier `dev.atlas.ide` read from its Linux directory name. On Darwin the zed, vscode and atlas scripts use those paths; Linux is unchanged. No macOS machine was available, so this is tested with a fake `uname`, not on macOS.
### Revision 6. The wrapper argv rule applies to `host-run` only
Decide 1 ruled the rewrite for `host-run` and `container-run`. PR #645 review found that only `host_run` keeps stdout clean for the extension, and S4.7 already makes the vscode integration host-only, so a container launcher set as the wrapper is now left for typer to refuse rather than run with a corrupted stream.
