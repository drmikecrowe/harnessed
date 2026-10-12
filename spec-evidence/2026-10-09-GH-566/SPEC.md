# SPEC — container-acp: take the project from session/new cwd

## Summary
**What it achieves.** One global editor entry, `harnessed container-acp <harness> --stack <name>`, works in every project, including when the editor reuses one agent process for several projects. The editor no longer needs a per-project entry with a hard-coded path, and Atlas no longer kills the agent while a pod starts.

**Why.** Atlas starts the agent in its own working directory, waits only 60 s for `initialize`, and sends every project's `session/new` to the one process it started. Today `container-acp` takes the project from its own working directory and answers `initialize` only after the pod is up.

**What changes.** In ACP mode, `container-acp` becomes a host-side proxy. It answers `initialize` at once from a per-harness reply held in the code. Each `session/new`, `session/load` or `session/resume` names a project. The first request for a project runs the existing launch for it as a child, replays `initialize` to that child, and forwards the request. Every later message goes to the child of the session it names. `session/list` for a project with no child gets an empty list. `container-run`, `container-exec`, `host-run` and `host-acp` do not change.

**Acceptance criteria in plain words.**
- AC-1: with no project path, the session runs in the project that `session/new` `cwd` names. A `cwd` that does not exist gets an error, and no pod starts.
- AC-2: `initialize` gets its reply before any pod work, well under 60 s.
- AC-3: `tools/acp-smoke.py` passes for omp and claude when started outside the project with no path, once with no pod and once with the pod up.
- AC-4: Atlas runs a prompt from a global entry in two projects in one Atlas run, through one agent process, each session in its own project. A path in the args wins over `cwd`.
- AC-5: the proxy's `initialize` reply matches the harness's own reply in `protocolVersion` and `agentCapabilities`.
- AC-6: `session/list` before any session gets an empty list, not an error; once the project's agent runs, the request reaches it.

**What must not change.** The interactive and `-exec` launches, `host-acp`, the ACP attach command, the rule that only JSON-RPC reaches stdout, the smoke script's existing `container-acp` and `host-acp` argv, and the refusal of a harness with no ACP mode.

**How each is proven.** AC-1, AC-2, AC-5 and AC-6 by unit tests on the proxy with fake agents, plus the live smoke run. AC-3 by the live smoke run on both harnesses. AC-4 by the live smoke run's two-project check and a manual Atlas run the engineer records in EVIDENCE, with the proxy's process tree as the one-process proof.

**Open decisions.** None. `session/list` reads "the project's pod is running" as "this process runs an agent for the project" (Decide 4), and routing moves the work to Tier 3 (Decide 5).

## Orientation
- Change: under `container-acp`, a proxy answers `initialize` itself, starts one relaunch child per project on that project's first session request, and routes every later line to the child of the session it names.
- Why: an editor that starts the agent outside the project, kills it after 60 s with no `initialize` reply, and reuses one process for every project, cannot use one global entry today.
- Touches: `src/harnessed/acpproxy.py`, `src/harnessed/launcher.py` (help text), `tools/acp-smoke.py`, `tests/test_acp_proxy.py`, `tests/test_acp_smoke.py`.
- Decide: the source of the canned `initialize` reply; what a session for a second project gets; the tier; what `session/list` does when the project's pod is up but this process runs no agent for it; whether the routing change re-tiers the work.
- Decided: Decide 1, a per-harness table in `acpproxy.py`, governs S1.2 and S5 (mcrowe, 2026-10-09). Decide 2, one child per project routed by session id, governs S9 (mcrowe, 2026-10-10; it replaces the 2026-10-09 ruling, a JSON-RPC error). Decide 3, Tier 2, governs the Verification contract (mcrowe, 2026-10-09). Decide 4, an empty list when this process runs no agent for the project, governs S10.1 (mcrowe, 2026-10-12). Decide 5, Tier 3, governs the Failure model and the Verification contract (mcrowe, 2026-10-12).
- Tier: 3 (mcrowe, 2026-10-12; it replaces Tier 2 from 2026-10-09)
- Issue: GH-566
- Isolation: worktree — `3-2-gh-566-acp-session-cwd` on branch `GH-566`, per CLAUDE.md.

## Failure model
Tier 3 (Decide 5, mcrowe, 2026-10-12). One line per way the change can hurt, and the layer that catches it.
- A line reaches the wrong project's agent, so work lands in the wrong tree: S9.2 tests, the routing property test, mutation.
- Two children's request ids collide and a reply reaches the wrong agent: S9.4 test, the routing property test.
- Two writers interleave inside one stdout line and the editor drops the channel: S4.7 test, the routing property test with long lines, live smoke.
- One project's slow launch stalls every other project: S9.3 test.
- A child that exits leaves its sessions routed to a dead pipe, or ends the proxy for every project: S4.5 test, hostile-input pass.
- Two spellings of one project start two pods: S9.5 test.
- The proxy never exits after the editor closes stdin, leaving pods and children behind: S4.4 test, live smoke's exit check.
- Malformed or hostile client input (not JSON, a non-object, a `sessionId` that is not a string, a huge line) crashes the reader thread and silences every project: the hostile-input pass, S9.6 test.

## Scenarios
### S1. `initialize` is answered at once
- S1.1 Given `container-acp omp --stack default` with a fake launch, when the client sends `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}`, then stdout gets a reply with `id` 1 and the launch has not been called.
- S1.2 Given the same for `claude`, when `initialize` arrives, then the reply's `result` equals the claude entry of the proxy's per-harness table in `acpproxy.py` (Decide 1, mcrowe, 2026-10-09), and the launch has not been called.
- S1.3 (boundary) Given a built image for stack `default` and no pod, when `tools/acp-smoke.py --no-path --launch-timeout 60` sends `initialize`, then the reply arrives within 60 s for omp and for claude.

### S2. The project comes from the session request's `cwd`
- S2.1 Given no path argument and a process working directory of an empty temp dir, when the client sends `session/new` with `cwd` = an existing directory P, then the launch runs with P as its project and the child receives `session/new` with `cwd` = P's container path, which path mirroring makes equal to P.
- S2.2 Given no path argument, when the first request for P is `session/load` or `session/resume` with `cwd` = P, then the launch runs with P as its project, as in S2.1.
- S2.3 (negative) Given no path argument, when `session/new` has `cwd` = `/nonexistent-gh566`, then the reply is a JSON-RPC error with code -32602 and a message naming that path, the launch is not called, and the proxy goes on reading stdin.
- S2.4 (negative) Given no path argument, when `session/new` has no `cwd` or a relative one, then the reply is a JSON-RPC error with code -32602, and the launch is not called.

### S3. A path in the args wins over `cwd`
- S3.1 Given path argument A, a process working directory C, and `session/new` with `cwd` = B, three different existing directories, when the session starts, then the launch runs with A as its project and the child receives `session/new` with `cwd` = A's container path.
- S3.2 (boundary) Given path argument A and the existing `--agent-start-folder sub` option, when the session starts, then the child receives `cwd` = the container path of `A/sub`.
- S3.3 (boundary) Given path argument A, when a later `session/new` names `cwd` = B, then it goes to A's child with `cwd` = A's container path, and no second launch runs.

### S4. The proxy forwards
- S4.1 Given a started child, when its first session request arrives, then the proxy first sends the child the client's own `initialize` request, reads the child's reply without writing it to stdout, and then forwards the session request; the child's reply reaches stdout unchanged.
- S4.2 Given a running session, when either side writes a line, including an agent-to-client request such as `session/request_permission`, then the other side receives it in order, unchanged except for the id rewrite of S9.4.
- S4.3 (boundary) Given a launch for P still running, when the client sends more lines for P, then they reach P's child after the first session request, in the order sent.
- S4.4 Given running children, when the client closes stdin, then every child's stdin is closed, and the proxy exits once every child has exited: with 0 when each exited 0, else with the first nonzero code.
- S4.5 Given children for P and Q, when P's child exits while stdin is open, then Q's sessions go on working; a later request that names one of P's sessions gets a JSON-RPC error with code -32603 and the message `agent for P exited`; a later `session/new` for P launches a new child.
- S4.6 (boundary) Given P's pod already up, started by another process such as an earlier `container-acp` or a `container-run`, when the proxy launches P's child, then the child runs the existing launch, which attaches to that pod, and no second pod for P is created. S7.2's pod-up run proves it live.
- S4.7 (negative) Given any launch, when it prints, then the output goes to stderr, and every stdout line is a JSON-RPC 2.0 message from the proxy or a child.

### S5. Drift in the canned reply is reported
- S5.1 Given a child whose `initialize` reply differs from the canned one in `protocolVersion` or `agentCapabilities`, when the proxy reads it, then it writes one stderr line `harnessed: ACP initialize drift: <harness>: <field>` per differing field.
- S5.2 (negative) Given a child whose reply equals the canned one in those two fields and differs only in `authMethods`, when the proxy reads it, then it writes no drift line. `authMethods` depends on the agent's login state (Revision 3), so the story drops it from AC-5.
- S5.3 Given `tools/acp-smoke.py`, when the launched process's stderr carries a line that starts `harnessed: ACP initialize drift`, then the run fails, so a live run on both harnesses proves AC-5.

### S6. A launch that fails answers the request
- S6.1 (negative) Given a launch that raises `typer.Exit(1)`, or a relaunch child that exits 1 before it answers `initialize`, for example for an unknown stack, when `session/new` arrives, then the reply is a JSON-RPC error with code -32603 and the message `launch failed (exit 1); see stderr`, no agent runs for that project, and sessions in other projects go on working (Revision 2).

### S7. The smoke script runs the way an editor does
- S7.1 Given `tools/acp-smoke.py <project> --stack default --harness omp --no-path`, when it runs, then it starts `container-acp` in a fresh temp dir with no path argument, the way `--verb host-acp` already starts, sends `session/new` with `cwd` = `<project>`, and passes. The same holds for `--harness claude`.
- S7.2 (boundary) Given S7.1, when it runs once with no pod and once with the pod up, then both runs pass.
- S7.3 Given S7.1 with `--check-cwd <B>`, when it runs, then the script's existing two-session check passes against one `container-acp` process: each session reports its own folder as its working directory.
- S7.4 (negative) Given `--no-path` with `--verb host-acp`, when the script parses its arguments, then it exits with a usage error, since `host-acp` never takes a path.

### S8. Atlas (manual)
- S8.1 Given an Atlas agent entry `harnessed container-acp claude --stack gortex-ghissues` with no project path, when the engineer, in one Atlas run, opens project A and prompts "print your working directory", then opens project B without quitting Atlas and prompts the same, then the replies name A's and B's container paths, and `ps --ppid <proxy pid> -o pid,args` taken while both sessions are open lists two relaunch children, one per project, under one proxy process.
- S8.2 (negative) Given an Atlas entry with path `/a` in its args, when Atlas sends `session/new` with `cwd` = `/b`, then the agent reports `/a`.
- S8.3 Given any session request that starts a child, when the child starts, then the proxy writes one stderr line `harnessed: ACP proxy <pid>: <project>`, so the Atlas log shows which process served each project.

### S9. Several projects in one process
- S9.1 Given a session in P on child C1, when `session/new` names `cwd` = Q, then a second child C2 is launched for Q, the request reaches C2 only, and C2's reply reaches stdout (Decide 2, mcrowe, 2026-10-10).
- S9.2 Given sessions in P and Q, when a request or notification carries `params.sessionId`, then it reaches only the child that created that session, learned from that child's reply to `session/new`, or from the `sessionId` of a `session/load` or `session/resume` it was sent.
- S9.3 (boundary) Given a session in P and a launch for Q still running, when the client sends lines for P's session, then they reach C1 without waiting for Q's launch.
- S9.4 Given C1 and C2 each sending an agent-to-client request with `id` 0, when the proxy forwards them, then the client sees two different ids, and the client's reply to each reaches the child that asked, carrying that child's original id 0.
- S9.5 (boundary) Given a session in P, when a later `session/new` names `cwd` = P, or P with a trailing slash, or a symlink to P, then it goes to C1 and no new launch runs: children are keyed by `Path(cwd).resolve()`. A relative `cwd` is refused as in S2.4.
- S9.6 (negative) Given no child created session X, when a request carries `params.sessionId` = X, then the reply is a JSON-RPC error with code -32602 and the message `unknown session: X`.
- S9.7 (negative) Given two or more children, when a request names no `sessionId` and no `cwd`, for example `authenticate`, then the reply is a JSON-RPC error with code -32600 and the message `cannot route <method>: it names no session`. With exactly one child, it goes to that child.

### S10. `session/list`
- S10.1 Given no child for project P, when the client sends `session/list` with `cwd` = P, for example `/home/mcrowe/Programming/Personal/harnessed/main` before any `session/new`, then the reply is `{"sessions": []}` and no launch runs, even when P's pod is up from an earlier launch (Decide 4, mcrowe, 2026-10-12).
- S10.2 Given a child for P, when the client sends `session/list` with `cwd` = P, then the request reaches that child and its reply reaches stdout unchanged.
- S10.3 (boundary) Given a `session/list` with no `cwd`, when a path argument A was given, then it is handled as S10.1 or S10.2 for A; with no path argument, the reply is `{"sessions": []}`.
- S10.4 (negative) Given any `session/list`, when the proxy answers it itself, then the reply is never a JSON-RPC error.

## Must NOT
- `container-run`, `container-exec` and `host-run` keep their project rule (path argument, else the working directory) and their `os.execvp` handoff. `test_the_interactive_attach_is_unchanged` passes.
- `container-acp` with a harness outside `_ACP_HARNESSES` exits 2 before any work. `test_a_harness_without_acp_is_refused_before_any_work` passes.
- `set_acp_mode(acp_mode)` stays before `_resolve_stack(` in `container_run`. `test_no_path_reaches_the_attach_unswapped` passes.
- `_acp_attach_cmd` returns the same commands. `TestTheAcpCommand` and `TestTheClaudeWrapper` pass.
- The composed ACP shell still sends its prologue to stderr. `test_everything_before_the_harness_goes_to_stderr` and `test_the_composed_shell_keeps_stdout_to_the_harness` pass.
- `host-acp` and `src/harnessed/acprelay.py` do not change. `tests/test_host_acp.py` passes.
- The smoke script's argv without `--no-path` does not change. `test_s8_3_container_acp_argv_is_unchanged` and `test_s8_host_acp_argv_names_no_project` pass.
- No new dependency. The proxy uses the standard library only.
- The supported ACP harnesses stay `omp` and `claude`.

## Touches
- `src/harnessed/acpproxy.py`: the single `_Session` becomes a table of children keyed by resolved project, each with its own handshake, stdout pump thread and pending-line queue; a session-id table filled from each child's session replies; the id rewrite for agent-to-client requests; launches on their own thread so one project's launch never blocks another's lines; the `session/list` answer; `DRIFT_FIELDS` drops `authMethods`; the per-child stderr line; the exit rule of S4.4 and S4.5. The relaunch callback in `src/harnessed/launcher.py` is called once per project and does not change.
- `src/harnessed/launcher.py`: the `container-acp` help text only (see Documentation).
- `tools/acp-smoke.py`: `--no-path`, which launches `container-acp` pathless from a fresh temp dir as `host-acp` already is; stderr read on a thread, echoed, and failing the run on a drift line. The 60 s deadline is the existing `--launch-timeout`, and the two-project check is the existing `--check-cwd`.
- `tests/test_acp_proxy.py`: S1.1, S1.2, S2–S6, S9 and S10 against fake agent scripts; the one-project-per-process tests are replaced by S9's; the routing property test and the hostile-input tests.
- `tests/test_acp_smoke.py`: `--no-path` argv and launch folder, S7.4, and the drift-line failure.

## Documentation
- The `container-acp` help text in `src/harnessed/launcher.py`: it says the project is the `cwd` of the client's first `session/new` or `session/load`; it becomes the `cwd` of each session request, one agent per project. No other doc in the repository names `container-acp`.

## Known limits
- A request other than `initialize`, a session request or `session/list` before the first session, for example `authenticate`, gets a JSON-RPC error: no agent runs yet to answer it. With two or more children, such a request gets S9.7's error.
- The `initialize` reply's `authMethods` is the table's entry for the harness, recorded from its own reply at the pinned version (omp: the one `agent` method; claude: an empty list). It can differ from the agent's own, which depends on its login state, so a logged-out user can see the wrong login options until a session starts.
- These rules are this SPEC's choices, not the story's: S4.5 (a child that exits, and its relaunch), S5 (the drift line), S9.7 (a request that names no session) and S10.3 (`session/list` with no `cwd`).
- A cold launch that must build the image can exceed Atlas's 120 s `session/new` limit. The story puts it out of scope.
- Each project costs one relaunch child and one pod, for as long as the editor keeps the process.
- Whether omp under `container-acp` connects the stack's MCP servers, which `host-acp` needed GH-580 for, is not checked here.
- S8 is manual: CI has no Atlas.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1.1, S1.2, S2–S6, S9, S10, S7.4 and every Must NOT test | `tools/run-tests.sh` passes; count not below the baseline plus the new tests |
| coverage | untested branches in the proxy | `--cov-fail-under=80` passes |
| property | routing under interleaving | a `hypothesis` test in `tests/test_acp_proxy.py`: for random interleavings of two fake children's lines and the client's lines, each session's lines arrive at its own side in order, every stdout line parses as JSON-RPC, and every forwarded reply carries the asking child's original id |
| mutation | tests that do not pin the routing | `mutmut` on `src/harnessed/acpproxy.py`, run by hand; every surviving mutant is killed by a new test or named in EVIDENCE with why it is equivalent |
| hostile input | the reader thread's robustness | the Failure model's last line, run against the proxy as unit tests; the reader thread survives each input and other projects keep working |
| types | type errors | pyright: no new error against the baseline |
| lint | style and bug patterns | ruff: 0 errors in src, tests, tools |
| shellcheck | shell defects | 0 findings |
| secrets | leaked credentials | gitleaks: 0 leaks |
| live smoke | S1.3, S5.3, S7.1–S7.3 on a real pod | `tools/acp-smoke.py --no-path --launch-timeout 60 --timeout 900` passes for omp and claude, no pod and pod up, and once each with `--check-cwd` |
| live CI | the container path (launcher.py is on the list from the earlier commits) | `live` and `live-docker` green on the PR |
| manual | S8.1, S8.2, S8.3 | the engineer records the Atlas replies, the `ps` listing and the stderr lines in EVIDENCE |
| adversary | defects the author missed | no confirmed finding open |
