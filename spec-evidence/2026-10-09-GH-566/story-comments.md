# Comments on GH-566

Oldest first, pulled from the tracker.

## 1. drmikecrowe, 2026-10-09T22:18:25Z

# Gate 1, story readiness

verdict: not-ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-4-6
tokens: 46888/244
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/claude-1000/-home-mcrowe-Programming-Personal-harnessed-3-2-gh-566-acp-session-cwd/d04d7160-f873-4193-92a8-58bfdbb2fed5/scratchpad/story-record.json
graded: 2026-10-09T22:18:21.302Z

## Reasons

- AC-4: unproven

## Findings

- SR-READINGS: "Atlas runs one prompt from a global agent entry with no project path in its args; boundary: the same entry, used in two different projects one after the other". Smallest fix: Add the expected outcome for the positive case: state that each prompt runs in the project that `session/new` `cwd` names, for example: 'Atlas runs one prompt from a global agent entry with no project path in its args and the session runs in the project that `session/new` `cwd` names; boundary: the same entry, used in two different projects one after the other, each session in its own project'

Fix the story and run /spec-evidence:story again.

## Record

```json
{
  "input": "Story",
  "type": "feature",
  "missing": [],
  "gaps": [
    "prompt 1: the author identifies hard-coding or caching agent capabilities per harness as the hard part, but no criterion checks that the `initialize` reply content is correct or usable by Atlas — timing is covered by AC-2, content is not",
    "prompt 2: AC-4 does not name the artifact that proves the session ran in the correct project — a reader must guess whether to check the working directory inside the session, a log line, or a path in a tool call",
    "prompt 3: an implementation could satisfy AC-1 through AC-3 by returning an empty or stub `initialize` reply immediately, and AC-4 could still pass if Atlas does not validate capabilities — the implementation would break real workflows but every criterion would be green"
  ],
  "fields": [
    {"name": "who", "state": "present"},
    {"name": "what", "state": "present"},
    {"name": "done-looks-like", "state": "present"},
    {"name": "example", "state": "present"}
  ],
  "readings": [
    {
      "ac": "AC-4",
      "readings": [
        "Atlas runs one prompt successfully (no crash, no error) using a global agent entry with no project path — the session runs wherever it happens to run",
        "Atlas runs one prompt and the session executes in the project that Atlas's `session/new` `cwd` names, verified by checking context inside the session"
      ]
    }
  ],
  "findings": [
    {
      "rule": "SR-READINGS",
      "quote": "Atlas runs one prompt from a global agent entry with no project path in its args; boundary: the same entry, used in two different projects one after the other",
      "smallest_fix": "Add the expected outcome for the positive case: state that each prompt runs in the project that `session/new` `cwd` names, for example: 'Atlas runs one prompt from a global agent entry with no project path in its args and the session runs in the project that `session/new` `cwd` names; boundary: the same entry, used in two different projects one after the other, each session in its own project'"
    }
  ],
  "deferred": [],
  "items": [
    {
      "ac": "AC-1",
      "status": "proven",
      "evidence": "Start `container-acp <harness> --stack <name>` from `/tmp`; send `session/new` with `cwd`=`/some/real/project`; confirm the session's working context is that project. Then send `session/new` with `cwd`=`/nonexistent`; confirm the response is a JSON-RPC error and no pod appears in `podman ps`."
    },
    {
      "ac": "AC-2",
      "status": "proven",
      "evidence": "With the stack image already built and no pod running, send `initialize`; measure the elapsed time to receipt of the reply — if it exceeds 60 s or if the reply arrives only after a pod starts (verified by `podman ps` timestamp), the criterion is false."
    },
    {
      "ac": "AC-3",
      "status": "proven",
      "evidence": "Run `tools/acp-smoke.py --harness omp` and `tools/acp-smoke.py --harness claude` each twice (first with no pod, second with the pod up) while `container-acp` was started outside the project with no project path in its args; if either invocation exits nonzero or emits a non-JSON-RPC-2.0 byte to stdout, the criterion is false."
    },
    {
      "ac": "AC-4",
      "status": "unproven",
      "evidence": "The criterion does not state where the session must run — 'Atlas runs one prompt' is satisfied whether the session lands in the correct project or not. Two outcomes both satisfy the text: session runs in the correct project, and session runs in the wrong project. The author would judge them differently but the criterion does not distinguish them."
    }
  ]
}
```

## Story

````
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

What: `harnessed container-acp` runs as a host-side proxy. It answers `initialize` at once, starts or attaches the pod on `session/new` for the project that request's `cwd` names, then forwards. A project path in the args still wins over `cwd`. One global editor entry then works in every project.

Done looks like: AC-1 to AC-4 pass.

Example: Atlas starts `harnessed container-acp claude --stack default` in Atlas's own directory and sends `session/new` with `cwd` = `/home/mcrowe/Programming/Personal/harnessed/main`. The agent runs in a pod for that project, at the container path `paths.container_project_path` gives it (`src/harnessed/emit.py:955`).

### Why

- **Atlas** starts the agent in Atlas's own working directory, not the project. Its host always passes `root_dir: None` (`crates/atlas-agent-servers/src/connection.rs:199-201`, `src-tauri/src/commands/agent_host.rs:408`). It does send the project root as `session/new` `cwd` (`src/features/chat/components/chat-panel.tsx:408-411`). Today that means one editor entry per project, with the path hard-coded.
- **Zed** starts the agent in the project's first root (`crates/agent_servers/src/acp/transport.rs`), so it works today. Other editors may not.

### Timeout

Atlas waits 60 s for `initialize` (`INITIALIZE_TIMEOUT`, `connection.rs:57`, no override) and 120 s for `session/new`. A cold launch that builds or creates a pod takes longer, so Atlas kills it. The fix is a host-side proxy: answer `initialize` at once, start or attach the pod on `session/new`, then forward.

### Hard part

The proxy has to answer `initialize` before the real agent runs. Agent capabilities differ per harness, so they must be hard-coded per harness or cached from an earlier run.

### Fallback (not chosen)

Defer only the project choice to `session/new`, and leave `initialize` to the agent. That fixes the per-project entries but not the timeout. The author chose the proxy on 2026-10-09.

Drafted by the assistant from the author's text; approved by the author 2026-10-09.
## Acceptance criteria
- AC-1: `container-acp <harness> --stack <name>` with no project path, started in a directory that is not the project, runs the session in the project that `session/new` `cwd` names; boundary: the start directory is one that holds no project, for example `/tmp`; negative: when `cwd` names a directory that does not exist, `session/new` returns a JSON-RPC error and no pod starts.
- AC-2: `initialize` gets its reply in under 60 s, with or without a pod running, before any pod starts or attaches; boundary: 60 s is Atlas's `INITIALIZE_TIMEOUT`, and the stack's image is already built; negative: the `initialize` reply never waits for the pod.
- AC-3: `tools/acp-smoke.py` passes for `--harness omp` and `--harness claude` when container-acp starts in a directory other than the project, with no project path in its args; boundary: one run with no pod (it creates one) and one with the pod up (it attaches), as the script's docstring asks; negative: a stdout byte that is not JSON-RPC 2.0 fails the run.
- AC-4: Atlas runs one prompt from a global agent entry with no project path in its args; boundary: the same entry, used in two different projects one after the other; negative: an entry that passes project path `/a` in its args with `session/new` `cwd` = `/b` runs the session in `/a`.
## Constraints
- Supported harnesses stay `omp` and `claude` (`_ACP_HARNESSES`, `src/harnessed/attachcmd.py:60`).
- A cold launch that must build the image is out of scope, including Atlas's 120 s `session/new` limit on such a launch.
- One process serving sessions in more than one project is out of scope here.
````

## 2. drmikecrowe, 2026-10-09T22:44:18Z

# Gate 1, story readiness

verdict: ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-4-6
tokens: 49990/349
rubric: rubric.md 4c2886dd973af290e392b5da5cdeb6f654611d2e87b0d02ee37757bab0a040af
record: /tmp/claude-1000/-home-mcrowe-Programming-Personal-harnessed-3-2-gh-566-acp-session-cwd/d04d7160-f873-4193-92a8-58bfdbb2fed5/scratchpad/story-record2.json
graded: 2026-10-09T22:44:14.223Z

## Reasons

none

## Record

```json
{
  "input": "Story",
  "type": "feature",
  "missing": [],
  "gaps": [
    "prompt 2: AC-4 names `paths.container_project_path` as the verification signal but does not say how the agent reports its working directory — a reader must guess whether to look at a tool call, a log line, or a prompt response",
    "prompt 3: AC-5 requires the proxy reply to match the harness's own `initialize` but does not say whether 'pinned versions' means the versions currently installed or versions recorded somewhere; a reader must guess where the reference values come from"
  ],
  "fields": [
    {"name": "who", "state": "present"},
    {"name": "what", "state": "present"},
    {"name": "done-looks-like", "state": "present"},
    {"name": "example", "state": "present"}
  ],
  "readings": [],
  "findings": [],
  "deferred": [],
  "items": [
    {
      "ac": "AC-1",
      "status": "proven",
      "evidence": "Start `container-acp <harness> --stack <name>` from `/tmp`; send `session/new` with `cwd`=`/some/real/project`; confirm the session's working context is that project. Then send `session/new` with `cwd`=`/nonexistent`; confirm the response is a JSON-RPC error and no pod appears in `podman ps`."
    },
    {
      "ac": "AC-2",
      "status": "proven",
      "evidence": "With the stack image already built and no pod running, send `initialize`; measure the elapsed time to receipt of the reply — if it exceeds 60 s or if the reply arrives only after a pod starts (verified by `podman ps` timestamp), the criterion is false."
    },
    {
      "ac": "AC-3",
      "status": "proven",
      "evidence": "Run `tools/acp-smoke.py --harness omp` and `tools/acp-smoke.py --harness claude` each twice (first with no pod, second with the pod up) while `container-acp` was started outside the project with no project path in its args; if either invocation exits nonzero or emits a non-JSON-RPC-2.0 byte to stdout, the criterion is false."
    },
    {
      "ac": "AC-4",
      "status": "proven",
      "evidence": "Run Atlas using a global agent entry with no project path in args; send `session/new` with `cwd` = `/project/A`; confirm the agent reports its working directory as `paths.container_project_path` for project A. Repeat with `cwd` = `/project/B`; confirm the agent reports the container path for B. Then use an entry that passes `/a` in args with `cwd`=`/b`; confirm the session runs in `/a`."
    },
    {
      "ac": "AC-5",
      "status": "proven",
      "evidence": "Run `container-acp` for `omp` and `claude`; capture the proxy's `initialize` reply; separately invoke the harness's own `initialize` for each; compare `protocolVersion`, `agentCapabilities`, and `authMethods` fields. If any field differs between the proxy reply and the harness's own reply for either harness, the criterion is false."
    }
  ]
}
```

## Story

````
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

What: `harnessed container-acp` runs as a host-side proxy. It answers `initialize` at once, starts or attaches the pod on `session/new` for the project that request's `cwd` names, then forwards. A project path in the args still wins over `cwd`. One global editor entry then works in every project.

Done looks like: AC-1 to AC-5 pass.

Example: Atlas starts `harnessed container-acp claude --stack default` in Atlas's own directory and sends `session/new` with `cwd` = `/home/mcrowe/Programming/Personal/harnessed/main`. The agent runs in a pod for that project, at the container path `paths.container_project_path` gives it (`src/harnessed/emit.py:955`).

### Why

- **Atlas** starts the agent in Atlas's own working directory, not the project. Its host always passes `root_dir: None` (`crates/atlas-agent-servers/src/connection.rs:199-201`, `src-tauri/src/commands/agent_host.rs:408`). It does send the project root as `session/new` `cwd` (`src/features/chat/components/chat-panel.tsx:408-411`). Today that means one editor entry per project, with the path hard-coded.
- **Zed** starts the agent in the project's first root (`crates/agent_servers/src/acp/transport.rs`), so it works today. Other editors may not.

### Timeout

Atlas waits 60 s for `initialize` (`INITIALIZE_TIMEOUT`, `connection.rs:57`, no override) and 120 s for `session/new`. A cold launch that builds or creates a pod takes longer, so Atlas kills it. The fix is a host-side proxy: answer `initialize` at once, start or attach the pod on `session/new`, then forward.

### Hard part

The proxy has to answer `initialize` before the real agent runs. Agent capabilities differ per harness, so they must be hard-coded per harness or cached from an earlier run.

### Fallback (not chosen)

Defer only the project choice to `session/new`, and leave `initialize` to the agent. That fixes the per-project entries but not the timeout. The author chose the proxy on 2026-10-09.

Drafted by the assistant from the author's text; approved by the author 2026-10-09.
## Acceptance criteria
- AC-1: `container-acp <harness> --stack <name>` with no project path, started in a directory that is not the project, runs the session in the project that `session/new` `cwd` names; boundary: the start directory is one that holds no project, for example `/tmp`; negative: when `cwd` names a directory that does not exist, `session/new` returns a JSON-RPC error and no pod starts.
- AC-2: `initialize` gets its reply in under 60 s, with or without a pod running, before any pod starts or attaches; boundary: 60 s is Atlas's `INITIALIZE_TIMEOUT`, and the stack's image is already built; negative: the `initialize` reply never waits for the pod.
- AC-3: `tools/acp-smoke.py` passes for `--harness omp` and `--harness claude` when container-acp starts in a directory other than the project, with no project path in its args; boundary: one run with no pod (it creates one) and one with the pod up (it attaches), as the script's docstring asks; negative: a stdout byte that is not JSON-RPC 2.0 fails the run.
- AC-4: Atlas runs one prompt from a global agent entry with no project path in its args, and the session runs in the project that `session/new` `cwd` names, shown by the agent reporting its working directory as that project's container path; boundary: the same entry, used in two different projects one after the other, each session in its own project; negative: an entry that passes project path `/a` in its args with `session/new` `cwd` = `/b` runs the session in `/a`.
- AC-5: the proxy's `initialize` reply carries the same `protocolVersion`, `agentCapabilities` and `authMethods` that the harness's own `initialize` returns; boundary: checked for both `omp` and `claude` at their pinned versions; negative: a reply that differs from the harness's own in any of those fields fails.
## Constraints
- Supported harnesses stay `omp` and `claude` (`_ACP_HARNESSES`, `src/harnessed/attachcmd.py:60`).
- A cold launch that must build the image is out of scope, including Atlas's 120 s `session/new` limit on such a launch.
- One process serving sessions in more than one project is out of scope here.
````
