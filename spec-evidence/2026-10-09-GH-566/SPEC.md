# SPEC — container-acp: take the project from session/new cwd

## Summary
**What it achieves.** One global editor entry, `harnessed container-acp <harness> --stack <name>`, works in every project. The editor no longer needs a per-project entry with a hard-coded path, and Atlas no longer kills the agent while a pod starts.

**Why.** Atlas starts the agent in its own working directory and waits only 60 s for `initialize`. Today `container-acp` takes the project from its own working directory and answers `initialize` only after the pod is up.

**What changes.** In ACP mode, `container-acp` becomes a host-side proxy. It answers `initialize` at once from a per-harness reply held in the code. On the first `session/new` or `session/load`, it picks the project, runs the existing launch, starts the harness as a child, replays `initialize` to it, and then forwards every line both ways. `container-run`, `container-exec` and `host-run` do not change.

**Acceptance criteria in plain words.**
- AC-1: with no project path, the session runs in the project that `session/new` `cwd` names. A `cwd` that does not exist gets an error, and no pod starts.
- AC-2: `initialize` gets its reply before any pod work, well under 60 s.
- AC-3: `tools/acp-smoke.py` passes for omp and claude when started outside the project with no path, once with no pod and once with the pod up.
- AC-4: Atlas runs a prompt from a global entry, in the right project, in two projects in turn. A path in the args wins over `cwd`.
- AC-5: the proxy's `initialize` reply matches the harness's own reply in `protocolVersion`, `agentCapabilities` and `authMethods`.

**What must not change.** The interactive and `-exec` launches, the ACP attach command, the rule that only JSON-RPC reaches stdout, and the refusal of a harness with no ACP mode.

**How each is proven.** AC-1, AC-2 and AC-5 by unit tests on the proxy with a fake agent, plus the live smoke run. AC-3 by the live smoke run on both harnesses. AC-4 by a manual Atlas run the engineer records in EVIDENCE.

**Open decisions.** None. The canned reply is a per-harness table in code, a second session for another project gets an error, and the change is Tier 2.

## Orientation
- Change: under `container-acp`, a proxy answers `initialize` itself and defers the project choice and the whole launch to the first `session/new` or `session/load`.
- Why: an editor that starts the agent outside the project, and kills it after 60 s with no `initialize` reply, cannot use one global entry today.
- Touches: `src/harnessed/acpproxy.py` (new), `src/harnessed/launcher.py`, `tools/acp-smoke.py`, `tests/test_acp_proxy.py` (new), `tests/test_acp_verb.py`.
- Decide: the source of the canned `initialize` reply; what a second session for another project gets; the tier.
- Decided: Decide 1, a per-harness table in `acpproxy.py`, governs S1.2 and S5 (mcrowe, 2026-10-09). Decide 2, a JSON-RPC error, governs S9.1 (mcrowe, 2026-10-09). Decide 3, Tier 2, governs the Verification contract (mcrowe, 2026-10-09).
- Tier: 2 (mcrowe, 2026-10-09)
- Issue: GH-566
- Isolation: worktree — `3-2-gh-566-acp-session-cwd` on branch `GH-566`, per CLAUDE.md.

## Scenarios
### S1. `initialize` is answered at once
- S1.1 Given `container-acp omp --stack default` with a fake launch, when the client sends `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}`, then stdout gets a reply with `id` 1 and the launch has not been called.
- S1.2 Given the same for `claude`, when `initialize` arrives, then the reply's `result` equals the claude entry of the proxy's per-harness table in `acpproxy.py` (Decide 1, mcrowe, 2026-10-09), and the launch has not been called.
- S1.3 (boundary) Given a built image for stack `default` and no pod, when `tools/acp-smoke.py` sends `initialize`, then the reply arrives within 60 s for omp and for claude.

### S2. The project comes from `session/new` `cwd`
- S2.1 Given no path argument and a process working directory of an empty temp dir, when the client sends `session/new` with `cwd` = an existing directory P, then the launch runs with P as its project and the child receives `session/new` with `cwd` = P's container path, which path mirroring makes equal to P.
- S2.2 Given no path argument, when the first session request is `session/load` with `cwd` = P, then the launch runs with P as its project, as in S2.1.
- S2.3 (negative) Given no path argument, when `session/new` has `cwd` = `/nonexistent-gh566`, then the reply is a JSON-RPC error with code -32602 and a message naming that path, the launch is not called, and the proxy goes on reading stdin.
- S2.4 (negative) Given no path argument, when `session/new` has no `cwd` or a relative one, then the reply is a JSON-RPC error with code -32602, and the launch is not called.

### S3. A path in the args wins over `cwd`
- S3.1 Given path argument A, a process working directory C, and `session/new` with `cwd` = B, three different existing directories, when the session starts, then the launch runs with A as its project and the child receives `session/new` with `cwd` = A's container path.
- S3.2 (boundary) Given path argument A and the existing `--agent-start-folder sub` option, when the session starts, then the child receives `cwd` = the container path of `A/sub`.

### S4. The proxy forwards
- S4.1 Given a started child, when the session starts, then the proxy first sends the child the client's own `initialize` request, reads the child's reply without writing it to stdout, and then forwards `session/new`; the child's `session/new` reply reaches stdout unchanged.
- S4.2 Given a running session, when either side writes a line, including an agent-to-client request such as `session/request_permission`, then the other side receives it unchanged and in order.
- S4.3 (boundary) Given a launch still running, when the client sends more lines, then they reach the child after `session/new`, in the order sent.
- S4.4 Given a running session, when the client closes stdin, then the child's stdin is closed and the proxy exits with the child's exit code; when the child exits first, the proxy exits with its exit code.
- S4.5 (negative) Given any launch, when it prints, then the output goes to stderr, and every stdout line is a JSON-RPC 2.0 message from the proxy or the child.

### S5. Drift in the canned reply is reported
- S5.1 Given a child whose `initialize` reply differs from the canned one in `protocolVersion`, `agentCapabilities` or `authMethods`, when the proxy reads it, then it writes one stderr line `harnessed: ACP initialize drift: <harness>: <field>` per differing field.
- S5.2 (negative) Given a child whose reply equals the canned one in those three fields, when the proxy reads it, then it writes no drift line.
- S5.3 Given `tools/acp-smoke.py`, when stderr carries a drift line, then the run fails, so a live run on both harnesses proves AC-5.

### S6. A launch that fails answers the request
- S6.1 (negative) Given a launch that raises `typer.Exit(1)`, or a relaunch child that exits 1 before it answers `initialize`, for example for an unknown stack, when `session/new` arrives, then the reply is a JSON-RPC error with code -32603 and the message `launch failed (exit 1); see stderr`, and no agent runs (Revision 2).

### S7. The smoke script runs the way an editor does
- S7.1 Given `tools/acp-smoke.py <project> --stack default --harness omp --no-path`, when it runs, then it starts `container-acp` in a fresh temp dir with no path argument, sends `session/new` with `cwd` = `<project>`, and passes. The same holds for `--harness claude`.
- S7.2 (boundary) Given S7.1, when it runs once with no pod and once with the pod up, then both runs pass.

### S8. Atlas (manual)
- S8.1 Given an Atlas agent entry `harnessed container-acp claude --stack default` with no project path, when the engineer opens project A and prompts "print your working directory", then the reply names A's container path; when they open project B with the same entry, the reply names B's.
- S8.2 (negative) Given an Atlas entry with path `/a` in its args, when Atlas sends `session/new` with `cwd` = `/b`, then the agent reports `/a`.

### S9. One project per process
- S9.1 (negative) Given a session in project P, when a later `session/new` or `session/load` names a different `cwd`, then the reply is a JSON-RPC error with code -32602 and the message `one project per process: P`, and the request does not reach the child (Decide 2, mcrowe, 2026-10-09).
- S9.2 (boundary) Given a session in project P, when a later `session/new` names `cwd` = P, then it is forwarded to the child unchanged.

## Must NOT
- `container-run`, `container-exec` and `host-run` keep their project rule (path argument, else the working directory) and their `os.execvp` handoff. `test_the_interactive_attach_is_unchanged` passes.
- `container-acp` with a harness outside `_ACP_HARNESSES` exits 2 before any work. `test_a_harness_without_acp_is_refused_before_any_work` passes.
- `set_acp_mode(acp_mode)` stays before `_resolve_stack(` in `container_run`. `test_no_path_reaches_the_attach_unswapped` passes.
- `_acp_attach_cmd` returns the same commands. `TestTheAcpCommand` and `TestTheClaudeWrapper` pass.
- The composed ACP shell still sends its prologue to stderr. `test_everything_before_the_harness_goes_to_stderr` and `test_the_composed_shell_keeps_stdout_to_the_harness` pass.
- No new dependency. The proxy uses the standard library only.
- The supported ACP harnesses stay `omp` and `claude`.

## Touches
- `src/harnessed/acpproxy.py` (new): the proxy. Line-delimited JSON-RPC on stdin and the saved real stdout; the per-harness `initialize` table; the project choice; the replay; the two-way pump; the drift check.
- `src/harnessed/launcher.py`: under `container-acp`, `container_run` hands control to the proxy after the harness checks. The proxy's launch callback starts the same `container-acp` argv again as a child, with piped stdin and stdout and the env `HARNESSED_ACP_DIRECT=1` and `HARNESSED_ACP_PROJECT=<project>`. That child skips the proxy, takes its project from the env when no path argument was given, and runs today's launch and exec handoff unchanged, `--rm` teardown included. The `container-acp` help text says the path is optional. (Revision 2) `--agent-start-folder` is an existing `container_run` option, resolved by `_resolve_start_dir` in `src/harnessed/attachcmd.py`; this change adds no flag.
- `tools/acp-smoke.py`: `--no-path`; `initialize` waits 60 s and `session/new` takes the launch timeout; fails on a drift line in stderr.
- `tests/test_acp_proxy.py` (new): S1.1, S1.2, S2–S6 and S9 against a fake agent script.
- `tests/test_acp_verb.py`: new tests for the proxy hand-off and the relaunch child's argv and env. The existing exec-handoff tests stay unchanged, because the relaunch child keeps that handoff (Revision 2).

## Documentation
- The `container-acp` help text in `src/harnessed/launcher.py`. No other doc in the repository names `container-acp`.

## Known limits
- A request other than `initialize`, `session/new` or `session/load` before the first session, for example `authenticate`, gets a JSON-RPC error: no agent runs yet to answer it.
- A cold launch that must build the image can exceed Atlas's 120 s `session/new` limit. The story puts it out of scope.
- One process serves one project (S9). The story puts more than one out of scope.
- S8 is manual: CI has no Atlas.

## Verification contract
| Layer | What it gates | Threshold |
|---|---|---|
| tests | S1.1, S1.2, S2–S6, S9 and every Must NOT test | `tools/run-tests.sh` passes; count not below the baseline plus the new tests |
| coverage | untested branches in the proxy | `--cov-fail-under=80` passes |
| types | type errors | pyright: no new error against the baseline |
| lint | style and bug patterns | ruff: 0 errors in src, tests, tools |
| shellcheck | shell defects | 0 findings |
| secrets | leaked credentials | gitleaks: 0 leaks |
| live smoke | S1.3, S5.3, S7.1, S7.2 on a real pod | `tools/acp-smoke.py --no-path` passes for omp and claude, no pod and pod up |
| live CI | the container path (launcher.py is on the list) | `live` and `live-docker` green on the PR |
| manual | S8.1, S8.2 | the engineer records the Atlas replies in EVIDENCE |
| adversary | defects the author missed | no confirmed finding open |
