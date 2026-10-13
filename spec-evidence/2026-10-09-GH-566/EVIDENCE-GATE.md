# Gate 2, evidence

verdict: ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 71962/231
record: work/evidence-record.json
graded: 2026-10-13T11:21:32.182Z

## Reasons

none

## Record

```json
{"gaps":["Live CI jobs (live, live-docker) have not run because the PR is not open. The report says so, and no story criterion depends on them.","AC-4 rests on a manual Atlas run. The agents' replies to pwd are 'reported by the engineer', and the proxy PID and Atlas log lines are quoted.","omp's two-project --check-cwd live run was not done because omp never answered a prompt in the default pod. AC-4 and AC-1 on omp rest on unit tests, and the omp live runs L3 and L4 cover initialize, session/new and stdout. No criterion requires the omp two-project run.","The report cites test ids, not path:line, so I did not open any test file. The grades rest on the report's mapping rows and live-run table."],"items":[{"ac":"AC-1","status":"proven","evidence":"No @SC tag. Clause rows in EVIDENCE.md: condition is test_acp_proxy.py::TestTheProjectComesFromCwd::test_cwd_names_the_project plus Live runs L1-L4. Boundary is L1-L4, launched from an empty /tmp/acp-smoke-launch-* folder. Negative is test_a_cwd_that_does_not_exist_is_an_error, with the launch never called. Mapping row S2.3."},{"ac":"AC-2","status":"proven","evidence":"Condition and negative: TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches (S1.1, S1.2). Boundary: Live runs L1/L4 (no pod) and L2/L3 (pod up) with --launch-timeout 60, replies in 0.4-0.7 s. Mapping row S1.3."},{"ac":"AC-3","status":"proven","evidence":"Live runs L1-L4 cover omp and claude, no pod and pod up, with --no-path from a different folder. Every run prints 'PASS: every stdout byte parsed as JSON-RPC'. Negative: tools/acp-smoke.py main() final drain, plus S4.7, where every test goes through _check_stdout. Mapping rows S7.1, S7.2."},{"ac":"AC-4","status":"proven","evidence":"Manual S8.1: one proxy, PID 3125599, served two projects in one Atlas run. The Atlas log lines, the ps --ppid output with two docker exec -w children, and the agent replies are quoted. Negative: Manual S8.2, a pinned entry, ran in .../harnessed/main although Atlas sent cwd=<worktree>. Also test_path_beats_cwd and test_a_second_project_gets_its_own_agent. Mapping rows S8.1, S8.2, S9.1."},{"ac":"AC-5","status":"proven","evidence":"Boundary: Live runs L1-L4 on claude-agent-acp 0.85.1 and omp 18.6.1 show no drift line, and a drift line fails the run. Negative: test_acp_smoke.py::test_s5_3_a_drift_line_fails_the_run and TestDrift::test_a_differing_reply_is_reported_per_field. Mapping rows S5.1, S5.3."},{"ac":"AC-6","status":"proven","evidence":"Condition: TestSessionList::test_before_any_session_the_list_is_empty and test_with_the_projects_agent_running_it_answers (the reply is the project's own agent's). Boundary: the pre-session/new startup call uses an existing cwd with no launch, and each test is a fresh serve, which stands in for an Atlas restart. Negative: test_a_bad_cwd_is_never_an_error. Mapping rows S10.1-S10.4."}]}
```
