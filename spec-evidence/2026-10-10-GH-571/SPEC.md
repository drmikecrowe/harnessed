# SPEC — host-acp: run a stack as an ACP agent on the host

## Summary
**What it achieves.** An editor such as Atlas, Zed or VS Code can start `harnessed host-acp <harness> --stack <name>` once and use it as an ACP agent for every project it opens. The agent runs on the host with the stack's config home and MCP servers, as `host-run` does, and each session runs in the folder the editor names.

**Why.** `container-acp` cannot serve one agent process across several projects, and Atlas reuses one process per entry. The host path has no pod, so the agent can take each session's folder natively.

**What changes.** A new verb `host-acp` does the per-stack half of `host-run` once, starts the agent (`omp acp`, or `claude-agent-acp` for claude), and relays JSON-RPC between the editor and the agent. It intercepts each `session/new`: the first time it sees a project folder, it runs a new per-project setup verb for that folder before it forwards the request. That verb is the per-project half of today's `host-run`, and `host-run` now calls it too. `build` offers to install the claude adapter. `build` and `install` also write the host ACP launcher `harnessed-acp-<harness>-<stack>-host`, and `tools/acp-smoke.py` can drive `host-acp`.

**Each criterion in plain words.**
- AC-1: stdout carries only JSON-RPC for omp and claude; all launch chatter goes to stderr; `opencode` is refused with exit 2 (S1).
- AC-2: `initialize` is answered in under 60 s; an unbuilt stack is refused with the build command named (S2).
- AC-3: one process serves two projects, each session in its own folder; a missing folder is a JSON-RPC error (S3).
- AC-4: the first session in a project runs the per-project setup verb once; a failure is a JSON-RPC error; `host-run` runs the same verb (S4).
- AC-5: a claude session sees only the stack's MCP servers unless `--no-strict-mcp-config` is given (S5).
- AC-6: `build <stack> claude` offers to install adapter 0.85.1; `host-acp claude` without it refuses on stderr (S6).
- AC-7: `build` writes the host ACP launcher for omp and claude, and `uninstall` removes it (S7).
- AC-8: `tools/acp-smoke.py` passes for omp and claude against `host-acp` from a non-project folder (S8).

**What must not change.** `host-run` behaves as today, and its existing tests pass unchanged. `container-acp` is untouched. A file in `~/.local/bin` that harnessed did not write is never overwritten.

**How each criterion is proven.** S1 to S7 are pytest tests. They use a stub ACP agent (a small Python script that speaks newline-delimited JSON-RPC) and a stub `harnessed` per-project verb, under a temporary `HOME` and `XDG_DATA_HOME`. S2.1, S3.4 and S8 run the real agents through `tools/acp-smoke.py` on the engineer's machine, and their output goes into the evidence. Then the gauntlet runs (tests, coverage at 80%, pyright, ruff, shellcheck, gitleaks), with scoped mutation testing, a property test on the relay, and the adversarial review for Tier 3. `live.yml` runs on the PR because `launcher.py` changes.

**Open decisions.** None. Ruled (mcrowe, 2026-10-10): the per-project verb is `project-setup`; under `host-acp` the agent gets per-stack environment only; `host-acp claude` runs an adapter at another version with a warning.

## Orientation
- Change: add `host-acp`, a host-native ACP relay that runs per-project setup on each new project's first `session/new`, and split that setup out of `host-run` into its own verb.
- Why: an editor reuses one agent process across projects, and only a host process can follow each session's folder.
- Touches: `launcher.py` (new `host-acp` and per-project verbs, `_launch_host` split, adapter offer in `build`), new `acprelay.py`, `launchscript.py` (`global_verbs`), new `__main__.py`, `tools/acp-smoke.py`, tests, README.
- Decide: Decide 1 (verb name), Decide 2 (agent env), Decide 3 (adapter version mismatch).
- Decided: Decide 1 B, the verb is `project-setup`, governs Terms and S4; Decide 2 A, per-stack env only, governs S5.4; Decide 3 B, another adapter version runs with a warning, governs S6.10 (mcrowe, 2026-10-10).

- Tier: 3 — a hand-rolled JSON-RPC relay with two threads and one shared writer, and a new public CLI verb.
- Issue: GH-571
- Isolation: worktree — `3-3-gh-571-host-acp`, branch `GH-571`.

Failure model (Tier 3):
- A launch line or a setup script's output reaches stdout and the editor's JSON parser breaks. Caught by S1.2 and S1.3.
- The relay interleaves two messages on stdout, so one line is not valid JSON. Caught by S3.5 (property test with concurrent writers).
- The relay changes a message it should pass through. Caught by S3.6 (property test: every non-`session/new` line is forwarded byte for byte).
- Per-project setup runs twice for one project, or runs for the launch folder. Caught by S4.2 and S1.4.
- The `host-run` split changes `host-run`'s behavior. Caught by S4.5 and the existing suite.

### Terms
- **Per-project setup verb**: the new CLI verb this SPEC adds, `project-setup` (mcrowe, 2026-10-10). Invoked as `harnessed project-setup <harness> <project> --stack <name>`. It holds the per-project half of `_launch_host`: the stack's services (`backend.wire_services`), the project tool env file (`_write_project_tool_env`), the recipe setup and init scripts (`backend.provision_tools(spec, ATTACH)`), and the setup notices (`_prompt_setup_notices`, `allow_terminal=False`). Run standalone, it first sets the per-project environment `host-run` sets: launch secrets for the project, recipe `env:`, the stack tool PATH, the stack mise env, and the folder-env contract (`harnessed_env`).
- **Per-stack setup**: every other step of `_launch_host` before the exec: harness and stack checks, `assemble`, omp block pruning, global launchers, capability warnings, settings merge, `materialize_config`, `seed_auth`, `provision_tools(spec, FIRST_START)`, and `wire_mcp`.
- **A folder that is not a project**: a fresh empty temporary directory, not inside any git work tree, with no `.env` or `.env.schema`.
- **The relay**: the `host-acp` process after the agent starts. It reads newline-delimited JSON-RPC from its stdin and writes each line to the agent's stdin, and reads the agent's stdout and writes each line to its own stdout. One lock guards every write to its stdout.
- **Stub agent**: a test script that answers `initialize`, answers `session/new` with a `sessionId`, and answers `session/prompt` with the `cwd` of that session in its reply text.
- **Stub setup verb**: a test script that appends its argv as one line to a file the test names, then exits with the code the test sets (0 unless the scenario says otherwise).
- **How the stubs are swapped in**: no environment variable or flag is added. `acprelay.run(agent_argv, agent_env, setup_argv)` takes the agent's argv and env, and a function that returns the setup command's argv for one project folder. `host-acp` passes the real values, built by two launcher functions: `_host_acp_agent_argv(harness, home, no_strict_mcp)` and `_project_setup_argv(harness, stack, project)`, which returns `[sys.executable, "-m", "harnessed", "project-setup", harness, str(project), "--stack", stack]`. Relay tests (S3.1 to S3.3, S3.5, S3.6, S4.1 to S4.4) call `acprelay.run` with `[sys.executable, <stub agent>]` and a function that returns `[sys.executable, <stub setup verb>]`, over pipes. Command-level tests (S1, S2.2, S5, S6.8, S6.10) run `host-acp` through typer's `CliRunner` with pytest `monkeypatch` replacing those two launcher functions and `assemble`, so no real agent or setup runs.
- **The user's own mise variables**: the variables `_snapshot_user_mise_env` saves before the stack's mise redirect, which `_restore_user_mise_env` puts back into the agent's env, as `host-run` does today.

## Scenarios
### S1. Stdout is JSON-RPC only (AC-1)
- S1.1 Given a built stack `s` with the stub agent in place of `omp acp`, started in a folder that is not a project, when the test sends `initialize` then `session/new` with `cwd` = an existing folder A, then each request gets a result, and every line on stdout parses as a JSON object with `"jsonrpc": "2.0"`.
- S1.2 (boundary) Given S1.1, and a stack recipe whose init script runs `echo INIT-OUT`, when `host-acp` starts and the first `session/new` for A runs the setup verb, then `INIT-OUT` and the `[INFO] Assembling` line appear on stderr, and neither appears on stdout.
- S1.3 Given S1.1 with the stub in place of `claude-agent-acp`, when the same exchange runs, then the S1.1 result holds for claude too.
- S1.4 (boundary) Given S1.1, when `host-acp` starts and before any `session/new`, then the setup verb has not run for the launch folder, and no project tool env file exists for the launch folder.
- S1.5 (negative) Given any stack, when `harnessed host-acp opencode --stack s` runs, then it exits 2, stderr says `opencode has no ACP mode; host-acp supports: omp, claude`, stdout is empty, and `assemble` was not called.

### S2. Startup time and an unbuilt stack (AC-2)
- S2.1 Given the stack `gortex-ghissues` built for omp and for claude, with adapter 0.85.1 installed and installs already cached by one earlier launch, when `tools/acp-smoke.py --verb host-acp --launch-timeout 60` runs for each harness, then `initialize` gets its result within 60 s. Run on the engineer's machine; the transcript goes into the evidence.
- S2.2 (negative) Given a stack `s` with no assembled profile (`paths.is_built("s", "omp")` is False), when `harnessed host-acp omp --stack s` runs, then it exits 1, stderr contains `harnessed build s omp`, stdout is empty, and `assemble` was not called.

### S3. One process, many project folders (AC-3)
The relay forwards each `session/new` with its `cwd` unchanged; the agent itself runs each session in that folder. The ACP protocol puts the session folder in `session/new`; that each real agent honours it is an assumption this plan does not verify ahead of the build. The automated scenarios prove the forwarding (S3.2). Only S3.4 proves that the real agents honour it, so S3.4 is required evidence, and a reply that names the launch folder fails it.
- S3.1 Given `host-acp` running the stub agent, when the test sends `session/new` with `cwd` = A, then `session/new` with `cwd` = B (both existing), and a `session/prompt` to each session, then the first reply names A and the second names B.
- S3.2 Given S3.1, then the agent received each `session/new` with its `cwd` unchanged.
- S3.3 (negative) Given `host-acp` running, when the test sends `session/new` with `cwd` = a path that does not exist and `id` = 7, then stdout gets `{"jsonrpc":"2.0","id":7,"error":{"code":-32602,"message":"session/new cwd does not exist: <path>"}}`, the setup verb did not run, and the agent never received that request.
- S3.4 (boundary) Given the real agents, when `tools/acp-smoke.py --verb host-acp --check-cwd <B>` runs with project A, then the agent's reply to a prompt asking for its working directory contains A for the first session and B for the second. Run on the engineer's machine for omp and claude; the transcript goes into the evidence.
- S3.5 (property) Given the relay with a stub agent that writes N messages of random size (1 B to 256 KiB) while the relay writes M error replies, when they run at the same time, then every line on stdout parses as JSON, and the count is N + M.
- S3.6 (property) Given any line from the editor that is not a JSON object with `"method": "session/new"` (including invalid JSON and blank lines), when the relay reads it, then the agent receives that line byte for byte.

### S4. Per-project setup runs once per project (AC-4)
- S4.1 Given `host-acp` with a stub setup verb that records its args, when the first `session/new` for A arrives, then the stub ran once with `<harness> <A> --stack <s>`, and it finished before the agent received the request.
- S4.2 (boundary) Given S4.1, when a second `session/new` for A arrives, then the stub did not run again. A path that resolves to A through a symlink counts as A.
- S4.3 (negative) Given a stub setup verb that exits 3 for A, when `session/new` with `cwd` = A and `id` = 9 arrives, then stdout gets an error reply for `id` 9 with code -32000 and a message containing A, and the agent never received that request.
- S4.4 (boundary) Given S4.3, when a second `session/new` for A arrives, then the setup verb runs again, since A was never set up.
- S4.5 Given `host-run`, when it launches, then it calls the same per-project setup function the verb runs (`_host_project_setup`, services and the project tool env file), once, and then runs ATTACH and the setup notices itself, as the verb does (Revision 3, mcrowe, 2026-10-10), after `provision_tools(spec, FIRST_START)` and before `wire_mcp`. Every existing test in `tests/test_launch_host.py`, `tests/test_host_run_recipes.py`, `tests/test_backend_seam.py`, `tests/test_exec_verbs.py`, `tests/test_no_strict_mcp_config.py` and `tests/test_host_setup.py` passes unchanged.
- S4.6 Given `harnessed project-setup omp <A> --stack s` run by itself, then it sets the per-project environment, runs the recipe setup and init scripts with `cwd` = A, writes the project tool env file for A, and exits 0.

### S5. MCP servers for claude (AC-5)
- S5.1 Given `host-acp claude --stack s`, when it starts the adapter, then the adapter's env holds `CLAUDE_CONFIG_DIR=<host home>`, `CLAUDE_CODE_EXECUTABLE=<catalog>/base/harnessed-claude-acp-cli`, `HARNESSED_MCP_CONFIG=<host home>/.mcp.json` and `HARNESSED_STRICT_MCP=1`, and `<host home>/.mcp.json` holds the stack's servers.
- S5.2 (boundary) Given `host-acp claude --stack s --no-strict-mcp-config`, then the adapter's env holds `HARNESSED_MCP_CONFIG` and no `HARNESSED_STRICT_MCP`, so the wrapper drops `--strict-mcp-config` and claude also loads the project's `.mcp.json`.
- S5.3 (negative) Given S5.1, then the wrapper's exec line passes `--strict-mcp-config`, which keeps the project's `.mcp.json` out. The existing wrapper tests in `tests/test_acp_verb.py` cover the wrapper's argv.
- S5.4 Given a global `~/.config/harnessed/.env` with `G=1`, a launch folder holding `.env` with `P=1`, and a stack recipe with `env: {R: "1"}`, when `host-acp omp --stack s` and `host-acp claude --stack s` start the agent, then the agent's env holds `G=1`, the stack tool bin dir first on `PATH`, the user's own mise variables, and the config-dir vars (`PI_CODING_AGENT_DIR` and `CLAUDE_CONFIG_DIR` for omp, `CLAUDE_CONFIG_DIR` for claude), and holds no `P`, no `R` and no `PROJECT_DIR`. A later `session/new` for a project changes none of it. Per Decide 2 A (mcrowe, 2026-10-10).

### S6. The claude adapter (AC-6)
The installed version is read from the `package.json` named `@agentclientprotocol/claude-agent-acp` above the real path of the `claude-agent-acp` found on PATH. It is installed when that version equals `build_args.CLAUDE_AGENT_ACP_VERSION.value` in `catalog/agents/claude/agent.yaml` (0.85.1 today). The version is read from the agent manifest, never written in code. Present on PATH at another version, or with no readable `package.json`, counts as not installed.
- S6.1 Given no `claude-agent-acp` on PATH, or one at version 0.84.0, and a terminal on stdin, when `harnessed build s claude` runs, then it asks exactly `I need to install \`npm i -g @agentclientprotocol/claude-agent-acp@0.85.1\` to support ACP -- is that OK? (y/n/c)`.
- S6.2 Given S6.1, when the answer is `y`, then it runs `npm i -g @agentclientprotocol/claude-agent-acp@0.85.1` as an argv list.
- S6.3 Given S6.1, when the answer is `c` and then the typed command `pnpm add -g @agentclientprotocol/claude-agent-acp@0.85.1`, then it runs that command through `bash -c`.
- S6.4 Given S6.1, when the answer is `n`, then it runs nothing and goes on with the build.
- S6.5 (boundary) Given adapter 0.85.1 on PATH, when `harnessed build s claude` runs, then it asks nothing.
- S6.6 (boundary) Given the install command exits non-zero, then `build` prints a warning naming the command on stderr and goes on; its exit status does not change.
- S6.7 (boundary) Given no terminal on stdin, when `harnessed build s claude` runs with the adapter missing, then it asks nothing, prints the install command on stderr, and goes on.
- S6.8 (negative) Given a built stack and no `claude-agent-acp` on PATH, when `harnessed host-acp claude --stack s` runs with stdin not a terminal, then it asks nothing, exits 1, stdout is empty, and stderr names `npm i -g @agentclientprotocol/claude-agent-acp@0.85.1`.
- S6.9 (boundary) Given `harnessed build s omp`, then it never checks the adapter.
- S6.10 (boundary) Given a built stack and `claude-agent-acp` 0.84.0 on PATH, when `harnessed host-acp claude --stack s` runs, then it prints a warning on stderr naming 0.84.0 and the pin 0.85.1, writes nothing to stdout before the agent starts, and starts the adapter. Per Decide 3 B (mcrowe, 2026-10-10).

### S7. The host ACP launcher (AC-7)
- S7.1 Given stack `s` and `HOME` a temp dir, when `harnessed build s omp` and `harnessed build s claude` run, then `~/.local/bin/harnessed-acp-omp-s-host` and `~/.local/bin/harnessed-acp-claude-s-host` exist, mode 0755, with line 2 `# harnessed:launcher v1` and the exec line `exec harnessed host-acp <harness> --stack s "$@"`.
- S7.2 (boundary) Given S7.1, when `harnessed build s claude` runs again, then one `harnessed-acp-claude-s-host` exists, byte-identical to the first.
- S7.3 Given S7.1, when `harnessed uninstall s claude` runs, then `harnessed-acp-claude-s-host` is gone.
- S7.4 (negative) Given `HOME` a temp dir, when `build` runs for `opencode`, `antigravity` and `codex`, then no `harnessed-acp-<harness>-s-host` exists.

### S8. The smoke script (AC-8)
`tools/acp-smoke.py` exists today and drives only `container-acp <harness> <project>`. It gains `--verb {container-acp,host-acp}` (default `container-acp`, so today's runs do not change). With `host-acp`, it runs `<harnessed> host-acp <harness> --stack <s>` with no project path in the args, with its working directory set to a folder that is not a project (a new temporary directory), and still sends `session/new` with `cwd` = the project. It gains `--check-cwd <B>`: after the first session's prompt, it opens a second session in B, asks each session for its working directory, and fails when a reply does not contain that session's folder.
- S8.1 Given the stack `gortex-ghissues` built for omp, when `uv run tools/acp-smoke.py <project> --stack gortex-ghissues --harness omp --verb host-acp --prompt "Reply with OK"` runs, then it prints `PASS: every stdout byte parsed as JSON-RPC` and exits 0.
- S8.2 Given the same for claude with adapter 0.85.1 installed, then the S8.1 result holds.
- S8.3 (boundary) Given no `--verb`, then the argv the script builds is today's `container-acp <harness> <project> --stack <s>`.

## Must NOT
- `host-run`'s argv, environment and folder do not change. Every existing test that does not pin the set of global launchers passes unchanged. This includes every test in the six files S4.5 names.
- Tests that pin "no host ACP launcher" change by design for AC-7: `tests/test_launchscript.py::test_s1_12_no_host_acp_launcher_is_written`, and any test that asserts the exact launcher set for omp or claude. The evidence lists each one, with its old and new assertion.
- `container-acp` and `attachcmd._acp_attach_cmd` do not change.
- `host-acp` never writes a local launcher into any folder and never registers an aoe row.
- The relay never changes a line it forwards (S3.6).
- A file in `~/.local/bin` without the harnessed sentinel is never overwritten or deleted.
- `build` never runs an install without a `y` or `c` answer.
- No credential is copied: the host home is reused as `host-run` uses it.

## Touches
- `src/harnessed/launcher.py`: the `host-acp` command; the `project-setup` command; `_launch_host` split into per-stack setup and a per-project function that both `host-run` and `project-setup` call; the adapter check and offer in `build`; the adapter check in `host-acp`.
- `src/harnessed/acprelay.py` (new): the relay, the `session/new` intercept, the error replies, the set of projects already set up.
- `src/harnessed/launchscript.py`: `global_verbs` adds `host-acp` for harnesses in `_ACP_HARNESSES`.
- `src/harnessed/__main__.py` (new): calls `harnessed.launcher.main`, so the relay can run `[sys.executable, "-m", "harnessed", "project-setup", ...]` with the same installation that runs it.
- `tools/acp-smoke.py`: `--verb` and `--check-cwd`.
- `tests/test_host_acp.py` (new): S1, S2.2, S3.1 to S3.3, S3.5, S3.6, S4, S5, S6.8, S6.10.
- `tests/test_launcher_build_adapter.py` (new): S6.1 to S6.7, S6.9.
- `tests/test_launchscript.py`, `tests/test_launcher_install.py`: S7, and the changed launcher-set tests.
- `tests/test_acp_smoke.py` (new): S8.3, the argv only.

## Documentation
- `README.md`: a `host-acp` section with an Atlas entry example.
- `.agents/skills/harnessed-catalog` does not change, because `host-acp` adds no catalog field.
- The wiki (`docs/`) is a separate delivery and is not in this PR.

## Known limits
- Environment that per-project setup derives does not reach the running agent (story constraint). The agent gets per-stack environment only (S5.4), so a tool the agent runs that needs a recipe `env:` value or a project secret lacks it under `host-acp`.
- `host-acp claude` runs an adapter at a version other than the pin, with a warning (S6.10).
- `session/load` and `session/resume` are relayed unchanged and do not trigger per-project setup. The story names only `session/new`.
- While the setup verb runs for one project, the relay holds every later editor message, `session/cancel` included, until the verb ends.
- The first launch after a stack change runs the recipe installs before the agent starts, which can take longer than 60 s. S2.1 measures a launch with the installs already cached.
- S2.1, S3.4 and S8 need real agent credentials and run on the engineer's machine, not in CI.
- Services start for the first project's folder; a service bound to one project's mount does not move for a later project.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1 to S7 and the existing suite | all pass; count not below the baseline plus the new tests |
| coverage | untested branches in `acprelay.py` and the new launcher code | 80% overall, branch coverage on |
| types | type errors | pyright 0 errors in changed files |
| lint | style and bug patterns | ruff 0 findings |
| shellcheck | shell scripts | 0 findings |
| secrets | leaked credentials | gitleaks 0 findings |
| mutation | weak assertions in `acprelay.py` and `launchscript.global_verbs` | no surviving mutant without a stated reason |
| property | S3.5, S3.6 | hypothesis, 200 examples each |
| live | container path unchanged (`launcher.py` touched) | `live.yml` both jobs green on the PR |
| manual | S2.1, S3.4, S8.1, S8.2 | transcripts in the evidence |
