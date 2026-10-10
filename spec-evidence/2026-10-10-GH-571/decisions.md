# Decisions — host-acp: run a stack as an ACP agent on the host

## Setup plan
- Isolation: worktree — `3-3-gh-571-host-acp` on branch `GH-571`, cut from `main` at `4f3f031`.
- Git: commit per scenario group (S1 to S8), signed, on `GH-571`. The queued label is `5a3dda9`.
- New dependencies: none. `hypothesis` is already in the dev extra.
- New files: `src/harnessed/acprelay.py`, `src/harnessed/__main__.py`, `tests/test_host_acp.py`, `tests/test_launcher_build_adapter.py`, `tests/test_acp_smoke.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage (80%, branch), types (pyright), lint (ruff on src, tests, tools), shellcheck and secrets (gitleaks). Mutation is not a declared layer, so it runs by hand: `HARNESSED_DIR=$PWD mise exec -- uv run --extra dev mutmut run "harnessed.acprelay.x_*"`, and the same for `harnessed.launchscript.x_global_verbs*`. mutmut gives typer commands zero mutants, so `host-acp` and `<setup-verb>` take manual mutants.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `live.yml` — 4 checks transcribed (pytest, ruff, pyright, shellcheck). `live.yml` triggers on `src/harnessed/launcher.py`.

## Facts this SPEC rests on
1. `_launch_host` (`launcher.py:3035-3308`) does, in order: harness check against `_HOST_HARNESSES` (claude, omp), project dir check, stack check, in-process `assemble`, omp block prune, global launchers plus local launcher and aoe row, `_resolve_launch_env(project_path)`, recipe load and capability warnings, `wire_services`, `_write_project_tool_env`, `_recipe_env`, `_apply_host_tool_path`, mise env snapshot and redirect, `harnessed_env`, settings merge, then under the home lock `materialize_config`, `seed_auth`, `provision_tools(FIRST_START)`, then `provision_tools(ATTACH)`, `_prompt_setup_notices`, `wire_mcp`, env build, `os.chdir(cwd)`, `os.execvpe`. — read directly.
2. `provision_tools(ATTACH)` runs `_host_run_setups` and `_host_run_inits` with `cwd=project_path` (`hostrun.py:745-848`), and does not need the home (`tests/test_backend_seam.py::test_attach_provisioning_does_not_need_the_home`). — research agent, test name confirmed.
3. `_host_run_installs` uses `project_path` to resolve recipe `env:` for the install scripts (`hostrun.py:598`, the `_recipe_env` call below it). — read directly, up to the script loop; the loop body was not read.
4. `wire_services` starts sidecars only when the stack declares services, with the project's mount path (`launcher.py:3001-3024`). — read directly.
5. host-run INFO lines go to stderr through `_err`, but `_say` (`proc.py:30-43`) and the init line (`hostrun.py:772`) go to stdout, and setup and init scripts inherit fd 1. `console.set_acp_mode` (`console.py:68-84`) points fd 1 at stderr and keeps the real fd for `acp_stdout()`. — research agent.
6. host-run has no built check; `paths.is_built(stack, harness)` is `profile_dir/.mcp.json` exists (`paths.py:160-162`). — read directly.
7. No ACP proxy exists in `src/`. `container-acp` is `container_run` under another name and passes JSON-RPC through untouched; it refuses an unsupported harness with exit 2 (`launcher.py:4185-4190`). — research agent.
8. `_ACP_HARNESSES = ("omp", "claude")` (`attachcmd.py:60`). In the container, claude runs `claude-agent-acp` with `CLAUDE_CODE_EXECUTABLE=/usr/local/bin/harnessed-claude-acp-cli`, `HARNESSED_MCP_CONFIG`, and `HARNESSED_STRICT_MCP=1` unless `--no-strict-mcp-config` (`attachcmd.py:80-86`). — research agent.
9. `catalog/base/harnessed-claude-acp-cli` is mode 0755 and runs `exec claude --mcp-config "$HARNESSED_MCP_CONFIG" ${HARNESSED_STRICT_MCP:+--strict-mcp-config} "$@"`. — read directly.
10. host-run writes `<home>/.mcp.json` and runs `claude --mcp-config <it> [--strict-mcp-config]`; omp gets `<home>/mcp.json` and `PI_CODING_AGENT_DIR=<home>` plus `CLAUDE_CONFIG_DIR=_host_omp_claude_dir(home)` (`launcher.py:2965-2999, 3280-3296`). — research agent.
11. `launchscript._GLOBAL_VERBS` already maps `host-acp` to `("acp-", "host")`, and `remove_globals` already removes it; `global_verbs` does not list it, so nothing writes it (`launchscript.py:81-180, 433-455`). `test_s1_12_no_host_acp_launcher_is_written` pins that. — research agent.
12. The adapter pin is `build_args.CLAUDE_AGENT_ACP_VERSION: {value: "0.85.1", spec: "npm:@agentclientprotocol/claude-agent-acp"}` (`catalog/agents/claude/agent.yaml:9-10`). No host-side install or version check exists in `src/`. — read directly; research agent for the absence.
13. `tools/acp-smoke.py` exists (140 lines) and runs `<harnessed> container-acp <harness> <project> --stack <s>`; it sends `initialize`, `session/new` with `cwd`, and an optional `session/prompt`, and fails on any non-JSON-RPC stdout line (`tools/acp-smoke.py:76-135`). It never checks the session's cwd. — read directly.
14. The `pnpm, never npm` rule is enforced on recipe content by the schema; it does not scan a string in `launcher.py`. The story fixes the prompt text with `npm i -g`, and `c` lets the user run a pnpm command. — searched `src/harnessed/schema.py` hits.
15. No `src/harnessed/__main__.py` exists; the console script is `harnessed = "harnessed.launcher:main"` (`pyproject.toml:19`). — read directly.
16. `_can_prompt()` is `sys.stdin.isatty() and not _EXEC_MODE` (`console.py:103-114`). The relay starts the setup verb with stdin from `/dev/null`, so the verb never prompts. — research agent.

## Gate 1 deferred items
- AC-4: the host-run tests are named in SPEC.md "S4. Per-project setup runs once per project" (S4.5) and "Must NOT".
- AC-8: `tools/acp-smoke.py` exists and is extended; see SPEC.md "S8. The smoke script".

## Intent review
- Gap 1 (cwd forwarded vs honoured): accepted; S3 now says S3.4 is the only proof that the real agents honour the folder, and is required.
- Gap 2 (agent env untested): accepted; S5.4 states the agent's env once Decide 2 is ruled.
- Gap 3 (additions): S7.5 cut. S6.6 and S6.7 declined: `build` runs without a terminal in CI and scripts, and a failed install must have defined behavior, so AC-6 cannot be built without them. S4.4 declined: it is the consequence of AC-4's "the first session/new for a project runs the verb" when the first run failed, not a new feature.
- Gap 4 (another installed version at build): accepted; S6 now counts another version as not installed, and S6.1 covers 0.84.0.

Round 2 (ran beside Gate 1a round 2, so nothing below changed the graded SPEC.md):
- Gap 1 (real agents may ignore the session cwd): accepted as a build-order note, not a SPEC change. `/spec-evidence:build` runs S3.4 against both real agents first, before RED. If an agent reports the launch folder, the build stops and the SPEC is revised visibly.
- Gap 2 (MCP servers that need recipe `env:`): declined as a SPEC change. It is the cost that Decide 2 A names, and the engineer ruled with that cost stated. Known limits already says it.
- Gap 3 (wrong version: build asks, host-acp runs): declined. That split is Decide 3 B as ruled; build installs the pin, and host-acp does not block a working session.
- Gap 4 (`__main__.py`, README): declined. `__main__.py` serves AC-4: the relay must run `project-setup` from the same installation that runs it, and no `__main__` exists (fact 15). The README section is the documentation that the SPEC's Documentation section requires.

## Decide calls

### Decide 1. What is the per-project setup verb called?
The story leaves the name to the plan (STORY.md, What). Existing host verbs are `host-run` and `host-exec` (`launcher.py:3446, 4640`).

- A. `host-prepare`. Cost: one more `host-*` verb in `--help`; reads as a host-backend step, which it is.
- B. `project-setup`. Cost: says nothing about the backend. (Corrected at ruling: a container twin can share the name, because paths map identically into the container.)
- C. `host-setup`. Cost: collides in reading with recipe `setup:` scripts and `tests/test_host_setup.py`, which mean something narrower.

Default: A. Ruling: B, `project-setup` (mcrowe, 2026-10-10). The engineer noted that paths map identically into the container, so one name serves both backends.
Changes: SPEC.md Terms, S4.6, Touches and Summary name the verb `project-setup`.

### Decide 2. What environment does the agent get under host-acp?
`host-run` puts project launch secrets, recipe `env:` and the folder-env contract (`PROJECT_DIR`, `MAIN_REPO_DIR`, …) into the agent's env, all derived from the project (`launcher.py:3151, 3186, 3216`). Under `host-acp` the agent starts before any project is known, and the story says derived env does not reach a running agent.

- A. Per-stack env only: global launch secrets (`_resolve_launch_env(None)`), the stack tool PATH, the user's mise env, and the config-dir vars. No recipe `env:`, no project secrets, no folder-env contract. Cost: a tool the agent runs that needs a recipe `env:` value (for example a `BEADS_*` connection) lacks it under `host-acp`.
- B. A, plus recipe `env:` resolved against the launch folder. Cost: a recipe value that names the project resolves to the editor's launch folder, which is wrong for every session.

Default: A. Ruling: A, per-stack env only (mcrowe, 2026-10-10).
Changes: SPEC.md adds S5.4 and states the limit under Known limits.

### Decide 3. Does host-acp claude run an adapter at a version other than the pin?
AC-6 defines "missing" for `build`, but not a different installed version for `host-acp`. CLAUDE.md pins every download.

- A. Refuse: a version other than the pin is treated as missing (exit 1, install command on stderr). Cost: a user who upgraded the adapter by hand cannot start until they reinstall the pin.
- B. Run any installed version and print a warning on stderr. Cost: the pin is not enforced at run time, so a session can run an adapter nobody tested.

Default: A. Ruling: B, run with a warning (mcrowe, 2026-10-10).
Changes: SPEC.md adds S6.10 and a Known limits line.

## Revisions
### Revision 1. Decide calls ruled
Decide 1 B, Decide 2 A, Decide 3 B (mcrowe, 2026-10-10), applied to SPEC.md before Gate 1a.
### Revision 2. Gate 1a round 1: PR-REFERENT fixed
Terms now define the stub setup verb and how both stubs are swapped in: parameters to `acprelay.run`, and `monkeypatch` on two launcher functions. The judge's example (an env var or PATH entry) was not used, because it would add a config surface the story did not ask for. Terms also define "the user's own mise variables", from the judge's gap 3.
### Revision 3. The ATTACH call stays in _launch_host
During GREEN, `tests/test_launch_host.py::TestHostHomeLock::test_lock_spans_the_installs_not_just_the_rebuild` failed: it reads the source of `_launch_host` for the call `backend.provision_tools(spec, ATTACH)`, to pin that setup scripts run after FIRST_START and outside the home lock. Moving that call into the shared function kept the order but removed the text. The engineer ruled (mcrowe, 2026-10-10) to keep the test unchanged: `_host_project_setup` holds the services and the project tool env file, and `host-run` and `project-setup` each run ATTACH and the setup notices themselves. S4.5 is reworded to match. The verb still runs all four steps (Terms).
