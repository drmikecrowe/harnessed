---
id: GH-571
type: feature
source:
  tracker: github
  external_id: GH-571
  url: https://github.com/drmikecrowe/harnessed/issues/571
  version: "unavailable: new issue"
---
# host-acp: run a stack as an ACP agent on the host
## Description
Who: a person who runs a harnessed stack as an ACP agent from an editor such as Atlas, Zed or VS Code, on the host, without a container.

What: `harnessed host-acp <harness> --stack <name>` starts omp (`omp acp`) or claude (the `claude-agent-acp` adapter, pinned to 0.85.1 in `catalog/agents/claude/agent.yaml`) as an ACP agent on stdio, with the stack's config home and MCP servers, the way `host-run` starts it interactively. Stdout carries only JSON-RPC. The launch does the per-stack setup once, in the folder it starts in. Each session's project comes from its `session/new` `cwd`: the first session in a project runs a new per-project setup verb for that project, which holds the per-project half of today's `host-run` (recipe init and setup scripts, the project env file). `host-run` runs the same verb, so it keeps working as it does today. The verb's name is set in the plan.

Done looks like: AC-1 to AC-8 pass.

Example: the Atlas entry `harnessed host-acp claude --stack gortex-ghissues` starts in Atlas's own folder. In the Atlas project `/home/mcrowe/Programming/Personal/harnessed` the agent reports that folder as its working directory; in a second Atlas project, `/home/mcrowe/Programming/Personal/harnessed/main`, in the same Atlas run, it reports that folder. Atlas starts one agent process per entry and reuses it across projects (Atlas log, 2026-10-10, GH-566).

### Background

`container-acp` (#566) is the container half and is parked: running it in Atlas showed that Atlas reuses one agent process across projects, which the container proxy does not yet support. The host path has no pod, so the agent answers `initialize` itself and handles each session's `cwd` natively. Global launchers (#565, merged) already name the host ACP launcher `harnessed-acp-<harness>-<stack>-host` and map `host-acp` to it in `src/harnessed/launchscript.py`. Registering the launcher with an editor automatically is #569; this story is standalone.

Drafted by the assistant from the author's text; approved by the author 2026-10-10.
## Acceptance criteria
- AC-1: `harnessed host-acp omp --stack <name>` and `harnessed host-acp claude --stack <name>`, on a built stack and started in a folder that is not a project, answer `initialize` and `session/new`, and every byte on stdout is a JSON-RPC 2.0 message; boundary: a launch that prints its usual INFO lines and runs recipe init scripts sends all of that output to stderr; negative: `harnessed host-acp opencode` exits 2 before any launch work.
- AC-2: on a built stack with the adapter installed, `initialize` gets its reply in under 60 s; boundary: 60 s is Atlas's `INITIALIZE_TIMEOUT`; negative: on a stack that is not built, `host-acp` exits non-zero with a stderr message naming `harnessed build <stack> <harness>`, and writes nothing to stdout.
- AC-3: one `host-acp` process receives `session/new` with `cwd` = folder A, then with `cwd` = folder B, both existing; each session runs in its own folder, and the agent asked for its working directory reports A, then B; boundary: Atlas with one global entry and two projects in one run; negative: a `session/new` whose `cwd` does not exist gets a JSON-RPC error, and no per-project setup runs.
- AC-4: the first `session/new` for a project runs the per-project setup verb for that project before the request reaches the agent; boundary: a second session in the same project does not run it again, and `host-run` runs the same verb with its existing tests passing unchanged; negative: when the verb fails, `session/new` gets a JSON-RPC error naming the project, and the agent never receives that request.
- AC-5: a claude session over `host-acp` sees the stack's MCP servers and, by default, only those, as `host-run` does; boundary: with `--no-strict-mcp-config` it also loads the project's `.mcp.json`; negative: a default launch does not load the project's `.mcp.json`.
- AC-6: `harnessed build <stack> claude`, when `claude-agent-acp` 0.85.1 is not installed, asks "I need to install `npm i -g @agentclientprotocol/claude-agent-acp@0.85.1` to support ACP -- is that OK? (y/n/c)"; `y` runs that command, `c` runs a command the user types instead, `n` skips it; boundary: with 0.85.1 already installed, the build asks nothing; negative: `harnessed host-acp claude` started by an editor with the adapter missing asks nothing, exits non-zero, writes nothing to stdout, and names the install command on stderr.
- AC-7: `harnessed build <stack> <harness>` writes `~/.local/bin/harnessed-acp-<harness>-<stack>-host` for omp and for claude, and `harnessed uninstall <stack> <harness>` removes it; boundary: a second build leaves one launcher with the same content; negative: `opencode`, `antigravity` and `codex` get no host ACP launcher.
- AC-8: `tools/acp-smoke.py` passes for omp and for claude against `host-acp`, started in a folder that is not the project and with no project path in its args.
## Constraints
- Supported harnesses: `omp` and `claude`, the same set as `container-acp` (`_ACP_HARNESSES`, `src/harnessed/attachcmd.py:60`).
- The host path's isolation level: no container, no firewall, no secrets broker.
- Environment variables that per-project setup derives do not reach an agent that is already running; the agent keeps the environment it started with.
- The folder `host-acp` starts in gets only per-stack setup, never per-project setup.
- Standalone: an editor entry is added by hand until #569 registers it.
