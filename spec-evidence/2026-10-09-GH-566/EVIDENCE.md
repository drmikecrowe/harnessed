## Evidence Report — container-acp: take the project from session/new cwd (Tier 3)

## Summary

**Delivered.** `harnessed container-acp <harness> --stack <name>` now works as one global editor entry for every project, including when the editor reuses one agent process for several projects, which Atlas does. A host-side proxy answers `initialize` at once from a per-harness table, starts one relaunch child (and pod) per project on that project's first session request, and routes every later line to the agent of the session it names. `session/list` before a project's agent runs gets an empty list. The smoke script gained `--no-path` and fails on an `initialize` drift line. Why: Atlas starts the agent in its own folder, waits only 60 s for `initialize`, and sends every project's `session/new` to one process, so the previous one-project-per-process proxy failed AC-4 in the 2026-10-10 Atlas run.

**Criteria and proof.**
- AC-1 (cwd picks the project; a missing cwd is an error and starts nothing): unit tests on the proxy, and the live smoke runs started from an empty folder with no path.
- AC-2 (`initialize` answered before any pod work, under 60 s): unit test that the launch is never called for `initialize`; live replies in 0.4–0.7 s with `--launch-timeout 60`, with no pod and with the pod up.
- AC-3 (smoke passes for omp and claude, outside the project, no path, no pod and pod up): four live smoke runs passed.
- AC-4 (Atlas, one global entry, two projects through one process; a path argument wins): manual Atlas run. One proxy process (PID 3125599) served the GH-566 worktree and `<second project, outside this repo>`, each agent reporting its own folder; the pinned entry reported `.../harnessed/main` while Atlas sent the worktree as `cwd`. Also the live smoke two-project check on claude, and unit tests.
- AC-5 (`protocolVersion` and `agentCapabilities` match the harness's own): no drift line in any of the live runs on omp or claude; the smoke script fails on one (tested).
- AC-6 (`session/list` empty before a session, the agent's reply after): unit tests.

**Not proven.** The `live` and `live-docker` CI jobs: they run on the pull request, which is not open yet.

**Judgment calls.** `session/list` reads "the project's pod is running" as "this process runs an agent for the project" (Decide 4). Routing moved the work to Tier 3 (Decide 5). A GH-565 test was pointed at the relaunch child, where the launch now runs (engineer's choice). Two stale `gortex-ghissues` pods with dead credential copies were removed so Atlas could log in; the credential design defect is epic #597, outside this story. The live smoke used stack `default`, rebuilt for omp and claude with the engineer's yes.

## Orientation
- Verdict: PASSED WITH LIMITS
- Delivered: `container-acp` serves every project an editor opens from one proxy process, one agent and pod per project, with `initialize` answered at once.
- Proven: 48/48 scenarios mapped; 47 pass, 1 (live CI) awaits the PR
- Not proven: live CI (`live`, `live-docker`) — runs on the PR, not opened yet

- Process: spec-evidence 0.0.1
- Spec: spec-evidence/2026-10-09-GH-566/SPEC.md (committed, dc47759)
- Spec approval: obtained from mcrowe (8ebf184, "GH-566: revised spec approved", 2026-10-12; first approval b6e331e)
- Intent review: three rounds changed the SPEC — S9.5 keys children by `Path(cwd).resolve()`; S4.6 states that a pod already up is attached, not duplicated; S7.3 requires two distinct projects; S2.1 asserts `paths.container_project_path(P)`; S5.3 names itself the guard against a stale table; Known limits names the canned `authMethods` per harness and which rules are the SPEC's own; S10.3 cites AC-6. Declined lines are in decisions.md.
- Source state: commit c94705f5c1235b769acda5efc2906052524f468e — the commit the final run and the review read
- Stamp:
```json
{
  "result": "green",
  "expected_layers": [
    "tests",
    "coverage",
    "types",
    "lint",
    "shellcheck",
    "secrets"
  ],
  "completed_layers": [
    "tests",
    "coverage",
    "types",
    "lint",
    "shellcheck",
    "secrets"
  ],
  "layer_seconds": {
    "tests": 310.718,
    "coverage": 359.788,
    "types": 14.541,
    "lint": 0.271,
    "shellcheck": 1.799,
    "secrets": 4.514
  },
  "failed": null,
  "exit_code": 0,
  "commit": "c94705f5c1235b769acda5efc2906052524f468e",
  "dirty": false,
  "written": "2026-10-12T18:05:14.217Z"
}
```
- Baseline: baseline-stamp.json at commit d3716079019809cc17bdc2df4863721033d002cc, green. It predates the rebase onto main 0.2.2; a full-suite run at 8ebf184 (after the rebase, before this build) gave 4272 passed, 1 failed (`test_s3_3_container_acp_writes_no_local_launcher`, fixed in ded66a1), 80 skipped.

### Spec → Test mapping

Test ids are in `tests/`. "Live" rows cite the runs in the Live runs table below. "Manual" rows cite the Atlas run below.

| Scenario | Test | Status |
|---|---|---|
| S1.1 | test_acp_proxy.py::TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches[omp] | pass |
| S1.2 | test_acp_proxy.py::TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches[claude]; ::test_every_acp_harness_has_a_canned_reply | pass |
| S1.3 | Live runs L1–L4 (`--launch-timeout 60`; replies 0.4–0.7 s) | pass |
| S2.1 | test_acp_proxy.py::TestTheProjectComesFromCwd::test_cwd_names_the_project[session/new] | pass |
| S2.2 | test_acp_proxy.py::TestTheProjectComesFromCwd::test_cwd_names_the_project[session/load], [session/resume] | pass |
| S2.3 | test_acp_proxy.py::TestTheProjectComesFromCwd::test_a_cwd_that_does_not_exist_is_an_error | pass |
| S2.4 | test_acp_proxy.py::TestTheProjectComesFromCwd::test_a_missing_or_relative_cwd_is_an_error | pass |
| S3.1 | test_acp_proxy.py::TestThePathArgumentWins::test_path_beats_cwd; TestTheMutationRun::test_a_session_request_with_no_cwd_gets_the_path_projects_cwd | pass |
| S3.2 | test_acp_proxy.py::TestThePathArgumentWins::test_the_start_folder_is_the_cwd_the_agent_gets | pass |
| S3.3 | test_acp_proxy.py::TestThePathArgumentWins::test_a_second_cwd_still_goes_to_the_path_project | pass |
| S4.1 | test_acp_proxy.py::TestTheProjectComesFromCwd::test_a_session_before_initialize_still_initializes_the_agent; TestTheMutationRun::test_the_agent_gets_the_clients_own_initialize; ::test_with_no_initialize_the_agent_gets_a_well_formed_one; ::test_a_stray_reply_before_the_init_reply_is_not_taken_for_it | pass |
| S4.2 | test_acp_proxy.py::TestForwarding::test_later_lines_reach_the_agent_in_order; TestTheMutationRun::test_a_raw_line_reaches_the_agent_byte_for_byte; ::test_a_non_json_line_from_the_agent_passes_and_the_session_goes_on | pass |
| S4.3 | test_acp_proxy.py::TestForwarding::test_later_lines_reach_the_agent_in_order; ::test_a_client_that_closes_at_once_still_gets_its_session | pass |
| S4.4 | test_acp_proxy.py::TestForwarding::test_the_exit_code_is_the_agents[1], [3]; ::test_every_agent_ends_and_the_first_nonzero_code_wins; ::test_all_agents_ending_cleanly_exit_zero; ::test_a_client_that_closes_at_once_still_gets_its_session | pass |
| S4.5 | test_acp_proxy.py::TestForwarding::test_one_agent_exiting_leaves_the_others_working; TestTheMutationRun::test_a_write_to_an_agent_that_stopped_reading_is_refused | pass |
| S4.6 | Live run L2 and L3 (pod up: attached, no second pod) | pass |
| S4.7 | every test through `_check_stdout` in test_acp_proxy.py; Live runs L1–L4 ("PASS: every stdout byte parsed as JSON-RPC") | pass |
| S5.1 | test_acp_proxy.py::TestDrift::test_a_differing_reply_is_reported_per_field | pass |
| S5.2 | test_acp_proxy.py::TestDrift::test_auth_methods_are_not_drift | pass |
| S5.3 | test_acp_smoke.py::test_s5_3_a_drift_line_fails_the_run; ::test_s5_3_stderr_still_reaches_the_terminal; Live runs L1–L4 (no drift line) | pass |
| S6.1 | test_acp_proxy.py::TestALaunchThatFails (all six tests); TestTheMutationRun::test_a_launch_without_an_output_pipe_answers_and_says_why; ::test_an_agent_whose_input_is_closed_at_launch_fails_the_launch; ::test_an_agent_that_stops_reading_after_initialize_refuses_the_waiting_request | pass |
| S7.1 | test_acp_smoke.py::test_s7_1_no_path_container_acp_argv_names_no_project; ::test_s7_1_no_path_starts_in_a_fresh_folder_and_sends_the_project_as_cwd; Live runs L1–L4 | pass |
| S7.2 | Live runs L1 (claude, no pod), L2 (claude, pod up), L3 (omp, pod up), L4 (omp, no pod) | pass |
| S7.3 | Live runs L1, L2 (`--check-cwd /tmp/gh566-smoke-b`, a different project, two pods) | pass |
| S7.4 | test_acp_smoke.py::test_s7_4_no_path_with_host_acp_is_a_usage_error | pass |
| S8.1 | Manual: Atlas run 2026-10-13, proxy 3125599 | pass |
| S8.2 | Manual: Atlas run 2026-10-13, pinned entry, proxy 2967442 | pass |
| S8.3 | test_acp_proxy.py::TestTheProcessIsNamed::test_each_agent_start_names_the_proxy_and_project; Manual: Atlas log lines | pass |
| S9.1 | test_acp_proxy.py::TestSeveralProjects::test_a_second_project_gets_its_own_agent | pass |
| S9.2 | test_acp_proxy.py::TestSeveralProjects::test_a_session_id_routes_to_the_agent_that_made_it; ::test_a_loaded_session_routes_to_its_project; test_routing_keeps_each_sessions_lines_with_its_agent_in_order (property) | pass |
| S9.3 | test_acp_proxy.py::TestSeveralProjects::test_a_slow_launch_does_not_hold_up_another_project | pass |
| S9.4 | test_acp_proxy.py::TestSeveralProjects::test_agent_request_ids_never_collide; TestTheMutationRun::test_an_agent_request_before_the_init_reply_is_renumbered; property test | pass |
| S9.5 | test_acp_proxy.py::TestSeveralProjects::test_one_project_by_any_spelling_is_one_agent[same], [slash], [symlink] | pass |
| S9.6 | test_acp_proxy.py::TestSeveralProjects::test_an_unknown_session_is_an_error; TestTheMutationRun::test_a_dropped_notification_is_named_on_stderr | pass |
| S9.7 | test_acp_proxy.py::TestSeveralProjects::test_a_request_naming_no_session_is_refused_with_two_agents; ::test_a_request_naming_no_session_goes_to_the_only_agent | pass |
| S10.1 | test_acp_proxy.py::TestSessionList::test_before_any_session_the_list_is_empty | pass |
| S10.2 | test_acp_proxy.py::TestSessionList::test_with_the_projects_agent_running_it_answers; TestTheMutationRun::test_session_list_cwd_becomes_the_start_folder | pass |
| S10.3 | test_acp_proxy.py::TestSessionList::test_no_cwd_uses_the_path_argument; ::test_no_cwd_and_no_path_is_empty | pass |
| S10.4 | test_acp_proxy.py::TestSessionList::test_a_bad_cwd_is_never_an_error | pass |
| Must NOT: container-run/-exec/host-run unchanged | test_acp_verb.py::TestContainerStdoutIsClean::test_the_interactive_attach_is_unchanged | pass |
| Must NOT: harness without ACP refused first | test_acp_verb.py::TestTheVerb::test_a_harness_without_acp_is_refused_before_any_work | pass |
| Must NOT: set_acp_mode before _resolve_stack | test_acp_verb.py::test_no_path_reaches_the_attach_unswapped | pass |
| Must NOT: _acp_attach_cmd unchanged | test_acp_verb.py::TestTheAcpCommand (5 tests); TestTheClaudeWrapper (4 tests) | pass |
| Must NOT: ACP prologue to stderr | test_acp_verb.py::TestContainerStdoutIsClean::test_everything_before_the_harness_goes_to_stderr; ::test_the_composed_shell_keeps_stdout_to_the_harness | pass |
| Must NOT: host-acp and acprelay.py unchanged | tests/test_host_acp.py (whole file, in the final run); `git diff b6e331e...HEAD -- src/harnessed/acprelay.py` is empty | pass |
| Must NOT: smoke argv without --no-path unchanged | test_acp_smoke.py::test_s8_3_container_acp_argv_is_unchanged; ::test_s8_host_acp_argv_names_no_project | pass |
| Must NOT: no new dependency; omp and claude only | `git diff b6e331e...HEAD -- pyproject.toml uv.lock` is empty; test_acp_proxy.py::TestInitializeIsAnsweredAtOnce::test_every_acp_harness_has_a_canned_reply | pass |
| Live CI on the PR | `live`, `live-docker` jobs | unverified |

Story criteria, clause by clause:

| Criterion clause | Test | Status |
|---|---|---|
| AC-1 condition: no path, started elsewhere, session in the `cwd` project | test_acp_proxy.py::TestTheProjectComesFromCwd::test_cwd_names_the_project; Live runs L1–L4 | pass |
| AC-1 boundary: started in a folder that holds no project | Live runs L1–L4 (launched in an empty `/tmp/acp-smoke-launch-*` folder) | pass |
| AC-1 negative: nonexistent `cwd` → JSON-RPC error, no pod | test_acp_proxy.py::TestTheProjectComesFromCwd::test_a_cwd_that_does_not_exist_is_an_error (launch never called) | pass |
| AC-2 condition: reply in under 60 s, before any pod work | test_acp_proxy.py::TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches; Live runs L1–L4 | pass |
| AC-2 boundary: 60 s, image built, with and without a pod | Live runs L1, L4 (no pod), L2, L3 (pod up), all `--launch-timeout 60` | pass |
| AC-2 negative: the reply never waits for the pod | test_acp_proxy.py::TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches | pass |
| AC-3 condition: smoke passes for omp and claude, outside the project, no path | Live runs L1–L4 | pass |
| AC-3 boundary: one run with no pod, one with the pod up | Live runs L1/L2 (claude), L4/L3 (omp) | pass |
| AC-3 negative: a non-JSON-RPC stdout byte fails the run | tools/acp-smoke.py `main()` final drain; Live runs L1–L4 print "PASS: every stdout byte parsed as JSON-RPC" | pass |
| AC-4 condition: Atlas, global entry with no path, agent reports the `cwd` project | Manual S8.1 | pass |
| AC-4 boundary: two projects, one Atlas run, one agent process | Manual S8.1 (proxy 3125599, two children); Live runs L1, L2; test_acp_proxy.py::TestSeveralProjects::test_a_second_project_gets_its_own_agent | pass |
| AC-4 negative: path `/a` in args, `cwd` = `/b` → runs in `/a` | Manual S8.2; test_acp_proxy.py::TestThePathArgumentWins::test_path_beats_cwd | pass |
| AC-5 condition: `protocolVersion` and `agentCapabilities` match the harness's own | Live runs L1–L4 (no drift line, which fails the run) | pass |
| AC-5 boundary: omp and claude at their pinned versions | Live runs L1, L2 (claude-agent-acp 0.85.1), L3, L4 (omp 18.6.1) | pass |
| AC-5 negative: a reply that differs fails | test_acp_smoke.py::test_s5_3_a_drift_line_fails_the_run; test_acp_proxy.py::TestDrift::test_a_differing_reply_is_reported_per_field | pass |
| AC-6 condition: no agent for the project → empty list; agent running → its reply | test_acp_proxy.py::TestSessionList::test_before_any_session_the_list_is_empty; ::test_with_the_projects_agent_running_it_answers | pass |
| AC-6 boundary: Atlas's startup call, before any `session/new`, `cwd` = `.../harnessed/main` | test_acp_proxy.py::TestSessionList::test_before_any_session_the_list_is_empty (sends `session/list` before any `session/new`) | pass |
| AC-6 negative: an error reply to `session/list` fails | test_acp_proxy.py::TestSessionList::test_a_bad_cwd_is_never_an_error | pass |

### Live runs (2026-10-12, stack `default`, from the worktree with `uv run`)

| Run | Command | Result |
|---|---|---|
| L1 | `tools/acp-smoke.py /tmp/gh566-smoke-a --stack default --harness claude --no-path --launch-timeout 60 --timeout 900 --check-cwd /tmp/gh566-smoke-b` (no pod) | `initialize answered in 0.7s`; `harnessed: ACP proxy 263216: /tmp/gh566-smoke-a`, `… /tmp/gh566-smoke-b`; each session reported its own folder; PASS |
| L2 | same as L1, pods up | `initialize answered in 0.5s`; proxy 279204 served both; each session reported its own folder; PASS |
| L3 | `tools/acp-smoke.py /tmp/gh566-smoke-a --stack default --harness omp --no-path --launch-timeout 60 --timeout 900` (pod up) | `initialize answered in 0.4s`; PASS |
| L4 | same as L3 on `/tmp/gh566-smoke-c` (no pod) | `initialize answered in 0.6s`; PASS |

### Manual Atlas run (2026-10-13, Atlas dev build, stack `gortex-ghissues`)

- S8.1: entry `harnessed-gh566` (`uv run --project <worktree> harnessed container-acp claude --stack gortex-ghissues`, no path). Atlas log: `session/new requested … cwd=/home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd` (10:54:59) and `… cwd=<second project, outside this repo>` (10:56:23); `agent stderr: harnessed: ACP proxy 3125599: <each project>`. `ps --ppid 3125599 -o pid,args`: 3147975 `docker exec … -w …/3-2-gh-566-acp-session-cwd harnessed-claude-gortex-ghissues-edc8292e …` and 3170303 `docker exec … -w <second project, outside this repo> harnessed-claude-gortex-ghissues-fd7619d4 …`. Agent replies (reported by the engineer): the worktree session "I'm in `/home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd`, according to `pwd`"; the infrastructure session "The current folder is `<second project, outside this repo>`, which I checked with `pwd`."
- S8.2: entry `harnessed-gh566-pinned-main` (path `/home/mcrowe/Programming/Personal/harnessed/main`). Atlas sent `cwd=…/3-2-gh-566-acp-session-cwd`; `harnessed: ACP proxy 2967442: /home/mcrowe/Programming/Personal/harnessed/main`; reply: "I'm in `/home/mcrowe/Programming/Personal/harnessed/main`, which I confirmed with `pwd`."
- S8.3: the `harnessed: ACP proxy <pid>: <project>` lines above.

### Gauntlet (final fresh run)
| Layer | Command | Status + result | Log |
|---|---|---|---|
| tests | `mise exec -- tools/run-tests.sh` | PASSED — 4339 passed, 80 skipped | work/tests.log |
| coverage | `mise exec -- uv run --extra dev pytest -q --cov=src --cov-branch --cov-fail-under=80` | PASSED — 86.36% total; `acpproxy.py` 99% | work/coverage.log |
| types | pyright with the uv interpreter | PASSED — 0 errors | work/types.log |
| lint | `mise exec -- uv run --extra dev ruff check src tests tools` | PASSED — all checks passed | work/lint.log |
| shellcheck | `shellcheck $(git ls-files "*.sh")` | PASSED — 0 findings | work/shellcheck.log |
| secrets | `gitleaks detect --no-banner --redact` | PASSED — no leaks found | work/secrets.log |
| property | `test_routing_keeps_each_sessions_lines_with_its_agent_in_order` (hypothesis, 25 examples, two agents, lines up to 200 000 bytes) | PASSED — in the tests layer | work/tests.log |
| mutation | `HARNESSED_DIR=$PWD uv run mutmut run "harnessed.acpproxy.*"`, `tests_dir` narrowed to test_acp_proxy.py and test_acp_verb.py for the run (pyproject.toml's documented workaround) | PASSED — 565 mutants: 531 killed, 8 timeout (the test hung: detected), 26 survived, every one equivalent (table below) | scratchpad mutmut-results-3.txt; finish__mutmut_13 rerun killed after a5230b5 |
| hostile input | TestHostileInput, TestTheMutationRun (bad JSON, non-objects, odd params, huge lines, unknown reply ids, non-JSON agent output, closed pipes) | PASSED — in the tests layer | work/tests.log |
| live smoke | `tools/acp-smoke.py --no-path --launch-timeout 60 --timeout 900`, omp and claude, no pod and pod up, `--check-cwd` on claude | PASSED — runs L1–L4 | above |
| manual | Atlas S8.1–S8.3 | PASSED | above |
| adversary | spec-evidence-adversary, two rounds | PASSED — two blocking findings, both fixed (d2afdd9, 903001b); none open | findings-code.md |
| live CI | `live`, `live-docker` on the PR | not run yet | — |

Equivalent mutants (26), each with why no test can tell it apart:
- `_Child.__init__` 5, 6, 7; `_Proxy.__init__` 17, 19; `open` 9: an initial value always overwritten, or only read after `run_child` sets it.
- `_Child.write` 2: the `stdin is None` branch is unreachable once a line can be written (only ready or handshaking agents are written to, and both have `stdin` set).
- `note` 3, 6, 7: the `flush` argument; stderr is line-buffered.
- `open` 56, 59, 60: the launch thread's `daemon` flag; `finish` joins every thread before `serve` returns.
- `open` 46; `list_sessions` 35, 36, 41, 42; `client_reply` 21, 26, 27: a `_Line` tag or `raw` value that `encode` never reads for that line (a non-raw kind is re-encoded from `msg`; a reply line has `msg` None and returns `raw` regardless of tag).
- `fail` 1, 3, 4: `fail` both marks the agent gone and removes it from `children`; each mutant drops one of the two, and the other still stops routing to it.
- `from_agent` 10, 11: the counter steps by -1 or 2; ids stay unique, which is all S9.4 requires.

### Layers not run as specified
- SUBSTITUTED: mutation — `tests_dir` was narrowed to the two ACP test files for the run, per pyproject.toml's note, because mutmut's copy dereferences symlinks and breaks two link-asserting tests elsewhere. It cannot detect a mutant only a test outside those two files would kill; such a mutant reports survived, so this can only under-count kills.
- live CI: not yet run — it starts when the PR is opened (`launcher.py` is on its list).

### Defect classes closed
- Generator: a launch-thread exit that leaves its waiting requests unanswered.
- Enumerated by: every `return` and `raise` path in `_Proxy.run_child` and `_Proxy.handshake` (src/harnessed/acpproxy.py).
- Sites: 4 — `run_child` launch raising `typer.Exit` (already correct: `fail`), launch raising anything else (fixed d2afdd9), no pipes (fixed d2afdd9), handshake failing (already correct: `fail`).
- Generator: closing an agent's stdin before its queued lines are written.
- Enumerated by: every caller of `_Child.close` and every `stdin.close()` in src/harnessed/acpproxy.py.
- Sites: 2 — `finish` (fixed 903001b: closes only ready agents), `run_child` after ready (already correct: closes only when `closing` is set, after the queue is flushed).

### Not reached by review
- Round 1: calls 4/10; hunts not reached: 2 (callers of acp_stdout and set_acp_mode: the Grep was blocked by a hook, so I could not confirm that acp_stdout() is valid in the parent proxy path before set_acp_mode runs), 6, 8, 9, 10; sites not opened: src/harnessed/launcher.py:4362-4380 (the code in container_run before the proxy hand-off, and set_acp_mode/acp_stdout definitions), src/harnessed/launcher.py _resolve_start_dir, .github/workflows/test.yml (coverage and tests gate arguments), SPEC.md and any EVIDENCE report
- Round 2: calls 3/10; hunts not reached: 1 (full comparison of the layer manifest with test.yml and lint.yml), 2 (callers of container_run and the other call sites of serve), 6, 9 (whether the Popen relaunch of sys.argv[0] works under pipx and uvx), 10; sites not opened: /home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/src/harnessed/console.py:68, /home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/tools/acp-smoke.py, /home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/tools/gauntlet-layers.json, /home/mcrowe/Programming/Personal/harnessed/3-2-gh-566-acp-session-cwd/spec-evidence/2026-10-09-GH-566/work/diff.txt (lines 1059-1502: the rest of the tests and the smoke tool)

### Agent rounds
| Agent | Round | Model | Tokens |
|---|---|---|---|
| context-pack | 1 | claude-sonnet-5-5 | 157806/1211 |
| spec-evidence-intent | 1 | claude-sonnet-5-5 | 62378/246 |
| spec-evidence-intent | 2 | claude-sonnet-5-5 | 63382/245 |
| spec-evidence-intent | 3 | claude-sonnet-5-5 | 63459/244 |
| spec-evidence-adversary | 1 | claude-sonnet-5-5 | 225670/3685 |
| spec-evidence-adversary | 2 | claude-sonnet-5-5 | 144177/1230 |

### Honest notes
- The adversary found two blocking defects the unit tests missed: a launch raising anything but `typer.Exit` killed the launch thread and left `session/new` unanswered, and `finish` closed a still-starting agent's stdin so a client that closed early lost its request. Both were reproduced RED first.
- The mutation triage was first delegated to a subagent that called about 70 survivors "equivalent", several wrongly (for example "the fake agent sends no requests", when it does). I re-triaged from the mutant diffs and wrote 14 more tests; the equivalence reasons above are mine.
- The `_serve` test helper first wrote every line at once, which no real client can do (a session id comes from a reply). It now waits for each session request's reply, as an editor does. One ordering test uses the interactive client.
- omp in a `default` pod never answered a prompt within 300 s, with the proxy and with it bypassed (`HARNESSED_ACP_DIRECT=1`), so the two-project `--check-cwd` live run is claude only. omp's `initialize`, `session/new` and stdout checks passed live. Cause not investigated; outside this story.
- Atlas S8 first hit a sign-in dialog: two old `gortex-ghissues` pods held per-pod credential copies with `expiresAt` 0, and the proxy's empty `authMethods` left Atlas no sign-in method. Removing the pods fixed it (a new pod re-seeds from the host). The credential design is epic #597. Atlas also exited once while starting a new pod (10:44); a pre-created pod avoided it, as in the 2026-10-10 run.
- Each Atlas launch of the gortex recipe writes an untracked `.mcp.json` into the project (#592); it is excluded from every commit.
- Whether omp under `container-acp` connects the stack's MCP servers (the GH-580 gap in `host-acp`) is not checked; it is in Known limits.
