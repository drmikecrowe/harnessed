# Decisions — container-acp: take the project from session/new cwd

## Setup plan
- Isolation: worktree — `3-2-gh-566-acp-session-cwd` on branch `GH-566`. CLAUDE.md forbids commits to `main`.
- Git: one commit per RED/GREEN slice; signed; the PR closes GH-566.
- New dependencies: none. The proxy uses `json`, `threading`, `subprocess` and `os`.
- New files: `src/harnessed/acpproxy.py`, `tests/test_acp_proxy.py`.
- Tooling audit: `tools/gauntlet-layers.json` declares tests, coverage, types, lint, shellcheck, secrets; all run. Live layer: `tools/acp-smoke.py` by hand, and `.github/workflows/live.yml`, which runs on the PR because `src/harnessed/launcher.py` is on its list. Mutation testing (`mutmut`) is not in the layer manifest; it runs only if Decide 3 picks Tier 3. No layer is UNAVAILABLE.
- Merge gate: `.github/workflows/test.yml`, `lint.yml`, `live.yml`, `pin-check.yml` — the layers above cover them.

## Facts this SPEC rests on
1. `container_run` resolves the project from the path argument, else `Path.cwd()` — `src/harnessed/launcher.py`, `anchor_path = Path(path).resolve() if path else Path.cwd()`.
2. The container path of a project equals its host path — `src/harnessed/paths.py:960`, `container_project_path` returns `Path(project_path)`.
3. In ACP mode, `_attach` exec's `podman exec -i … bash -l -c <shell>` with the real stdout restored, or runs it as a child under `--rm` — `src/harnessed/launcher.py`, `_attach`.
4. `set_acp_mode` swaps fd 1 to stderr and saves the real fd; `acp_stdout()` returns it — `src/harnessed/console.py`.
5. `_ACP_HARNESSES = ("omp", "claude")` — `src/harnessed/attachcmd.py:60`.
6. `tools/acp-smoke.py` waits `--launch-timeout` 900 s for `initialize` today, because the reply waits for the pod; it sends `session/new` with `cwd` = the project — `tools/acp-smoke.py`. Since the rebase onto main (GH-571), it also has `--verb host-acp`, which launches pathless from a `mkdtemp` folder (`main()`), and `--check-cwd <B>`, which opens a second session in one process and checks each session's reported folder (`_check_cwd`). `_launch_argv` always passes the path for `container-acp`, and stderr is inherited, not read.
7. Two tests in `tests/test_acp_verb.py` encode the ACP exec handoff: `test_stdout_is_restored_before_the_exec` and `test_the_rm_child_gets_the_clients_channel`. The story's proxy replaces that handoff in ACP mode, so they change with it; this is the story's decision, not a loosening.
8. No Markdown file in the repository names `container-acp`.
9. ACP `session/list` takes an optional `cwd` and `cursor`, and replies `{"sessions": [...], "nextCursor"?}` — `@agentclientprotocol/sdk` 0.12.0, `dist/schema/types.gen.d.ts`, `ListSessionsRequest` and `ListSessionsResponse`.
10. Both canned replies advertise `sessionCapabilities.list`, and the proxy refuses `session/list` before a session with `no session yet` — `src/harnessed/acpproxy.py`, `INITIALIZE_RESULTS` and `before_session`. Atlas calls it at startup (story comment, 2026-10-10).
11. `host-acp`'s relay already serves several projects from one agent and sends every stdout write through one lock — `src/harnessed/acprelay.py`, `run`. It does not change here; the proxy follows its stdout rule.
12. Agent sessions persist on disk in the stack's home whether a pod runs or not, so a pod being up says nothing about whether sessions exist to list. Inference from Revision 3's Atlas run and the persisted-home design (ARCHITECTURE.md); not tested here.

## Decide calls

### Decide 1. Where does the canned `initialize` reply come from?
The proxy must answer before the agent runs (story, "Hard part"). AC-5 requires the reply to match the harness's own.

- A. A table in `acpproxy.py`, one entry per harness, filled from each harness's own reply at its pinned version. Cost: a version bump that changes capabilities needs a table edit; S5's drift line and the smoke run catch it.
- B. A cache file written from the child's real reply on each run, with the table as the first-run fallback. Cost: a cache file under the data dir, invalidation by version, and still a table for the first run.

Default: A. Ruling: A, a table in code (mcrowe, 2026-10-09).
Changes: Orientation `Decided:` line; S1.2 and S5 read the table.

### Decide 2. What does a second session for a different project get?
The story puts one process serving more than one project out of scope.

- A. A JSON-RPC error -32602, `one project per process: <P>`. A second session for the same project is forwarded. Cost: an editor that reuses one process across projects must start a new one.
- B. Forward it to the running agent unchanged. Cost: the agent runs in project P while the editor believes it is in another; files go to the wrong tree.

Default: A. Ruling: A, a JSON-RPC error (mcrowe, 2026-10-09).
Changes: Orientation `Decided:` line; S9.1 states the error.

- C. One relaunch child and pod per project, each line routed by session id. Cost: a child table, a session-id table, an id rewrite for agent-to-client requests, and one pod per project for the process's life.

Ruling, replacing A: C, one child per project routed by session id (mcrowe, 2026-10-10; Revision 3). Atlas reuses one process across projects, so A fails AC-4.
Changes: Orientation `Decided:` line; S9 rewritten; S4.4, S4.5 and S6.1 name several children.

### Decide 3. Tier 2 or Tier 3?
The proxy adds a two-thread pump (concurrency) and a stdin reader shared between the handshake and the pump.

- A. Tier 2: the full loop and the adversary. Cost: no mutation or property run on the pump.
- B. Tier 3: add a failure model, property tests on line forwarding, and mutation testing on `acpproxy.py`. Cost: about one more hour; `mutmut` is not in the layer manifest and must be run by hand.

Default: A. Ruling: A, Tier 2 (mcrowe, 2026-10-09).
Changes: Orientation `Tier:` line.

### Decide 4. What does `session/list` get when the project's pod is up but this process runs no agent for it?
AC-6 says a project "with no pod running" gets an empty list and one "with that project's pod running" gets the agent's reply. A pod can be up from an earlier launch while this proxy has no child for it, for example right after Atlas restarts. Fact 12: the pod's state does not decide whether sessions exist.

- A. Read "the pod is running" as "this process runs an agent for the project". No child: `{"sessions": []}`. Cost: after an editor restart, past sessions do not list until a session opens in that project; the SPEC reads AC-6's words this way, and Gate 1a may call it a reading.
- B. Ask podman whether the project's pod is up; if it is, launch a child (an attach, about 49 s in the Atlas run) and forward. Cost: an editor's startup `session/list` starts an agent per project with a pod up, and can outlast the editor's wait for that reply.

Default: A. Ruling: A, an empty list when this process runs no agent for the project (mcrowe, 2026-10-12).
Changes: S10.1.

### Decide 5. Does the routing change move the work to Tier 3?
Decide 3 chose Tier 2 for one child and two threads. Routing adds a thread per child, a launch thread, two shared tables and an id rewrite (S9).

- A. Stay Tier 2: the full loop and the adversary. Cost: no property or mutation run on the routing.
- B. Tier 3: add a failure model, property tests on routing (random interleavings of two children's lines keep each session's order and ids), and mutation testing on `acpproxy.py`. Cost: about two more hours; `mutmut` is not in the layer manifest and runs by hand.

Default: B. Ruling: B, Tier 3 (mcrowe, 2026-10-12). `hypothesis` and `mutmut` are already dev dependencies in `pyproject.toml`, so no dependency is added.
Changes: Orientation `Tier:` line; the Failure model section; Verification contract.

## Intent review
- Gap 1 (path argument and a third working directory): accepted. S3.1 now names a process working directory C different from both.
- Gap 2 (S9.1 points at an open Decide 2): accepted. S9.1 takes the ruling's behavior once Decide 2 is ruled.
- Gap 3 (no rule that the proxy never builds): declined. The launch keeps its existing build behavior, for example `--recipe` builds a minted stack. The story puts a cold build out of scope for its criteria, not out of the product; forbidding a build would change working behavior. Known limits names it.

## Intent review, round 2
- Gap 1 (S2.1 host path or container path): accepted. S2.1 now says the child gets P's container path, equal to P under path mirroring (Fact 2).
- Gap 2 (S2.4 is extra behavior): declined. A missing or relative `cwd` names no project, and the proxy must answer the request somehow. The alternative is to fall back to the process's own working directory, which is the very behavior the story removes. An error is the smallest answer that launches nothing.

## Intent review, Revision 4
- Gap 1 (which `authMethods` the canned reply holds): accepted. Known limits names the table's entry per harness.
- Gap 2 (rules the story never asked for): accepted. Known limits marks S4.5, S5, S9.7 and S10.3 as this SPEC's choices.
- Gap 3 (AC-6 narrowed to "a child in this process"): left to Decide 4, asked in this round.
- Gap 4 (a pod already up from another process): accepted. S4.6 states that the child's existing launch attaches.
- Gap 5 (two spellings of one project): accepted. S9.5 keys children by `Path(cwd).resolve()` and names a trailing slash and a symlink.

## Intent review, Revision 5
- Gap 1 (AC-6's "pod running" read as "a child in this process"): declined. The story's author and the engineer are one person, and they ruled this reading in Decide 4 (mcrowe, 2026-10-12) after the cost was put to them.
- Gap 2 (S7.3's two folders could be one project): accepted. S7.3 requires two distinct projects, neither inside the other.
- Gap 3 (S5 and S8.3 add behavior no criterion asks for): declined. S5.3 is how the live run proves AC-5 against each harness's own reply at its pinned version, which a unit test against a fake cannot. S8.3 is the one-process proof the engineer asked for on 2026-10-12, and Known limits marks both as the SPEC's choices.
- Gap 4 (S2.1 asserts equality with P instead of `paths.container_project_path`): accepted. S2.1 asserts the function's value.

## Intent review, Revision 6
- Gap 1 (AC-6 narrowed): declined, as in the Revision 5 review. Decide 4 is ruled (mcrowe, 2026-10-12).
- Gap 2 (S5 and S10.3 are inventions): S10.3 accepted in part: it serves AC-6's negative, since ACP makes `cwd` optional and any error reply fails AC-6; it now says so. S5 declined: it is the live proof of AC-5.
- Gap 3 (Tier 3 is larger than the story): declined. Decide 5 ruled Tier 3 deliberately (mcrowe, 2026-10-12).
- Gap 4 (nothing fails when a pin moves and the table goes stale): accepted. S5.3 now states it is that guard.

## Revisions
### Revision 1. Gate 1a round 1, PR-REFERENT
S3.2 and Touches now say `--agent-start-folder` is an existing `container_run` option, resolved by `_resolve_start_dir`. Citation only; no scenario's meaning changed.
### Revision 2. The launch is a relaunch of the same command, not a refactor of `container_run`
Found at RED, after approval. The approved Touches split `container_run`'s body into a callback and changed `_attach` to return a piped child in ACP mode. Starting the same `container-acp` argv again as a child, with the project in `HARNESSED_ACP_PROJECT` and `HARNESSED_ACP_DIRECT=1`, reaches the same scenarios and leaves `container_run`'s 260-line body, the exec handoff, the `--rm` teardown and their tests unchanged. No scenario's Given, When or Then changed; S6.1 now also names the child that exits before `initialize`, and "no child starts" became "no agent runs", because a relaunch child does start and exits. Touches for `launcher.py` and `tests/test_acp_verb.py` changed to match.
### Revision 3. Parked: Atlas reuses one process per entry, so Decide 2 fails AC-4
Found in the manual Atlas run, 2026-10-10. Atlas does not start a new agent process per project: a second project's `session/new` reached the running `harnessed-gh566` process and got `one project per process` (Atlas log, 12:41:21 and 12:42:52 UTC). Decide 2's error therefore fails AC-4's boundary, and the story's constraint "one process serving more than one project is out of scope" contradicts AC-4 for Atlas. The engineer chose to serve several projects per process (one relaunch child and pod per project, routed by session id), which reopens the story (Gate 1) and the plan (Gate 1a). Also found: inside the `gortex-ghissues` pod, claude-agent-acp's `authMethods` differ from the canned table, so that field depends on login state and a fixed table cannot hold it. Parked at `aisdlc-in-progress` while a host-mode ACP story ships first.
### Revision 4. Several projects per process, after the story's second Gate 1
The story was revised and graded `ready` again on 2026-10-12: its out-of-scope line is gone, AC-4 names one Atlas run, AC-5 drops `authMethods`, and AC-6 is new. The SPEC follows: Decide 2 takes ruling C, S9 becomes routing by session id, S10 answers `session/list`, S5 drops `authMethods` from the drift check, S2.2 and S3.3 cover `session/resume` and a path argument with a second `cwd`, S8.1 and S8.3 add the one-process proof the engineer asked for, and the smoke script's container checks dropped in the rebase are re-added on top of main's script: `--no-path` reuses the `host-acp` launch, the 60 s deadline is the existing `--launch-timeout`, the two-project check is the existing `--check-cwd`, and the drift-line failure is new (S7). `/spec-evidence:plan` does not run at `aisdlc-in-progress`, so its steps ran by hand with no label move, per loop.md's rule that the SPEC is revised visibly during the task.
### Revision 5. Gate 1a round 1 on Revision 4: PR-REFERENT ×2, PR-SCOPE ×2
S5.2 and S6.1 cited "Revision 3" and "Revision 2", which the SPEC never defines; each now states its reason inline. S4.5 (a child that exits, and its relaunch) and S9.7 (a request that names no session) named no criterion; the engineer kept both and ties them to AC-4 (mcrowe, 2026-10-12), and Known limits no longer lists them as the SPEC's own choices.
### Revision 6. Gate 1a round 2 on Revision 5: PR-SCOPE on S8.3
S8.3 (the per-child stderr line) named no criterion. The engineer ties it to AC-4, whose boundary needs proof that one agent process served both projects (mcrowe, 2026-10-12). A new run of the Gate 1a step follows.
