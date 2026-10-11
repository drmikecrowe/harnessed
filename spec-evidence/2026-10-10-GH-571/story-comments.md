# Comments on GH-571

Oldest first, pulled from the tracker.

## 1. drmikecrowe, 2026-10-10T16:32:17Z

# Gate 1, story readiness

verdict: ready
story: GH-571
process: spec-evidence 0.0.1
model: claude-sonnet-4-6
tokens: 47656/244
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/claude-1000/-home-mcrowe-Programming-Personal-harnessed-3-2-gh-566-acp-session-cwd/d04d7160-f873-4193-92a8-58bfdbb2fed5/scratchpad/story-record-571.json
graded: 2026-10-10T16:32:12.826Z

## Reasons

none

## Record

```json
{
  "input": "Story",
  "type": "feature",
  "missing": [],
  "gaps": [
    "prompt 2: 'started in a folder that is not a project' — a reader has to guess what qualifies; is it any folder that has never been used as a cwd with host-acp, or any folder without a .git root, or something else?",
    "prompt 3: AC-5 says the session sees 'the stack's MCP servers and, by default, only those'; a stack with zero MCP servers configured satisfies this with an empty server list, which may not be what the author intends when verifying the criterion against a real stack"
  ],
  "fields": [
    {"name": "who", "state": "present"},
    {"name": "what", "state": "present"},
    {"name": "done-looks-like", "state": "present"},
    {"name": "example", "state": "present"}
  ],
  "readings": [],
  "findings": [],
  "deferred": [
    {
      "ac": "AC-4",
      "why": "the boundary 'host-run runs the same verb with its existing tests passing unchanged' requires knowing the current host-run test suite to verify no regression"
    },
    {
      "ac": "AC-8",
      "why": "whether tools/acp-smoke.py already exists or must be authored as part of this story can only be settled against the codebase"
    }
  ],
  "items": [
    {
      "ac": "AC-1",
      "status": "proven",
      "evidence": "launch both commands on a built stack in a non-project folder; capture stdout; parse each line as JSON-RPC 2.0 — any line that is not valid JSON-RPC fails; then launch with 'opencode' and check exit code equals 2"
    },
    {
      "ac": "AC-2",
      "status": "proven",
      "evidence": "start host-acp on a built stack, send initialize, record elapsed time; if elapsed >= 60 s the criterion fails; on an unbuilt stack run host-acp, check exit code is non-zero, stdout is empty, and stderr contains the string 'harnessed build <stack> <harness>'"
    },
    {
      "ac": "AC-3",
      "status": "proven",
      "evidence": "send session/new with cwd=A, ask the agent its working directory, verify it returns A; send session/new with cwd=B, ask again, verify B; then send session/new with a nonexistent path and verify the response is a JSON-RPC error object"
    },
    {
      "ac": "AC-4",
      "status": "proven",
      "evidence": "send first session/new for project P; verify observable side-effects of per-project setup (recipe init scripts ran, project env file written) exist before the agent replies; send second session/new for P; verify the setup side-effects are not repeated (e.g. no second log entry, env file mtime unchanged); then run a setup verb that exits non-zero and verify session/new returns a JSON-RPC error naming the project"
    },
    {
      "ac": "AC-5",
      "status": "proven",
      "evidence": "start host-acp without --no-strict-mcp-config; query the MCP server list the claude session sees; verify it equals exactly the stack's declared servers; start again with --no-strict-mcp-config; verify the project .mcp.json servers are also present; in the default launch verify .mcp.json servers are absent"
    },
    {
      "ac": "AC-6",
      "status": "proven",
      "evidence": "uninstall claude-agent-acp, run 'harnessed build <stack> claude', capture stdout, verify the exact prompt text appears and that y/c/n each produce the documented outcome; install 0.85.1, run build again, verify no prompt; launch host-acp claude without the adapter (editor-style, no tty), verify exit code non-zero, stdout empty, stderr contains the npm install command"
    },
    {
      "ac": "AC-7",
      "status": "proven",
      "evidence": "run 'harnessed build <stack> omp' and 'harnessed build <stack> claude'; verify ~/.local/bin/harnessed-acp-omp-<stack>-host and ~/.local/bin/harnessed-acp-claude-<stack>-host exist; run build a second time for each and verify file count is still one with identical content; run 'harnessed uninstall <stack> <harness>' and verify both files are gone; run build for opencode, antigravity, codex and verify no harnessed-acp-*-host file appears"
    },
    {
      "ac": "AC-8",
      "status": "proven",
      "evidence": "run 'python tools/acp-smoke.py' targeting host-acp for omp, started from a non-project folder with no project path in its args; verify exit 0; repeat for claude; a non-zero exit or missing file fails the criterion"
    }
  ]
}
```

## Story

````
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
````
