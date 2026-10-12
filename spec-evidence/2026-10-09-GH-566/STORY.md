---
id: GH-566
type: feature
source:
  tracker: github
  external_id: GH-566
  url: https://github.com/drmikecrowe/harnessed/issues/566
  version: "unavailable: the adapter's pull returns no updated stamp"
---
# container-acp: take the project from session/new cwd
## Description
Who: a person who runs a harnessed stack as an ACP agent from an editor such as Atlas or Zed.

What: `harnessed container-acp` runs as a host-side proxy. It answers `initialize` at once, starts or attaches the pod on `session/new` for the project that request's `cwd` names, then forwards. A project path in the args still wins over `cwd`. One process serves every project the editor opens in it: each project gets its own pod, and each message goes to the pod of the session it names. One global editor entry then works in every project.

Done looks like: AC-1 to AC-6 pass.

Example: Atlas starts `harnessed container-acp claude --stack default` in Atlas's own directory and sends `session/new` with `cwd` = `/home/mcrowe/Programming/Personal/harnessed/main`. The agent runs in a pod for that project, at the container path `paths.container_project_path` gives it (`src/harnessed/emit.py:955`).

### Why

- **Atlas** starts the agent in Atlas's own working directory, not the project. Its host always passes `root_dir: None` (`crates/atlas-agent-servers/src/connection.rs:199-201`, `src-tauri/src/commands/agent_host.rs:408`). It does send the project root as `session/new` `cwd` (`src/features/chat/components/chat-panel.tsx:408-411`). Today that means one editor entry per project, with the path hard-coded.
- **Atlas reuses one agent process per entry.** A second project's `session/new` reaches the process the first project started (Atlas log, 2026-10-10, 12:41:21 and 12:42:52 UTC). One process per project would fail AC-4.
- **Zed** starts the agent in the project's first root (`crates/agent_servers/src/acp/transport.rs`), so it works today. Other editors may not.

### Timeout

Atlas waits 60 s for `initialize` (`INITIALIZE_TIMEOUT`, `connection.rs:57`, no override) and 120 s for `session/new`. A cold launch that builds or creates a pod takes longer, so Atlas kills it. The fix is a host-side proxy: answer `initialize` at once, start or attach the pod on `session/new`, then forward.

### Hard part

The proxy has to answer `initialize` before the real agent runs. Agent capabilities differ per harness, so they must be hard-coded per harness or cached from an earlier run.

### Fallback (not chosen)

Defer only the project choice to `session/new`, and leave `initialize` to the agent. That fixes the per-project entries but not the timeout. The author chose the proxy on 2026-10-09.

Drafted by the assistant from the author's text; approved by the author 2026-10-12.
## Acceptance criteria
- AC-1: `container-acp <harness> --stack <name>` with no project path, started in a directory that is not the project, runs the session in the project that `session/new` `cwd` names; boundary: the start directory is one that holds no project, for example `/tmp`; negative: when `cwd` names a directory that does not exist, `session/new` returns a JSON-RPC error and no pod starts.
- AC-2: `initialize` gets its reply in under 60 s, with or without a pod running, before any pod starts or attaches; boundary: 60 s is Atlas's `INITIALIZE_TIMEOUT`, and the stack's image is already built; negative: the `initialize` reply never waits for the pod.
- AC-3: `tools/acp-smoke.py` passes for `--harness omp` and `--harness claude` when container-acp starts in a directory other than the project, with no project path in its args; boundary: one run with no pod (it creates one) and one with the pod up (it attaches), as the script's docstring asks; negative: a stdout byte that is not JSON-RPC 2.0 fails the run.
- AC-4: Atlas runs one prompt from a global agent entry with no project path in its args, and the session runs in the project that `session/new` `cwd` names, shown by the agent reporting its working directory as that project's container path; boundary: the same entry, used in two different projects one after the other in one Atlas run (switching projects without quitting Atlas), so one agent process serves both, each session in its own project; negative: an entry that passes project path `/a` in its args with `session/new` `cwd` = `/b` runs the session in `/a`.
- AC-5: the proxy's `initialize` reply carries the same `protocolVersion` and `agentCapabilities` that the harness's own `initialize` returns; boundary: checked for both `omp` and `claude` at their pinned versions; negative: a reply that differs from the harness's own in either field fails.
- AC-6: `session/list` for a project with no pod running gets an empty session list, not an error; with that project's pod running, the request goes to the pod and the agent's own reply comes back; boundary: Atlas's startup call, sent before any `session/new`, for example with `cwd` = `/home/mcrowe/Programming/Personal/harnessed/main`; negative: a JSON-RPC error reply to `session/list` fails.
## Constraints
- Supported harnesses stay `omp` and `claude` (`_ACP_HARNESSES`, `src/harnessed/attachcmd.py:60`).
- A cold launch that must build the image is out of scope, including Atlas's 120 s `session/new` limit on such a launch.

