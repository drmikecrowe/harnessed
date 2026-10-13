# Gate 2, evidence

verdict: ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 63110/226
record: work/evidence-record.json
graded: 2026-10-13T11:31:22.588Z

## Reasons

none

## Record

```json
{"gaps":["Live CI jobs (live, live-docker) are not run until the PR opens. No criterion depends on them.","AC-4 manual Atlas replies are 'reported by the engineer'. The Atlas log lines and ps output are quoted in the report, so I graded it proven.","AC-3 omp: the report says omp never answered a prompt within 300 s. The two-project --check-cwd run is claude only. The omp smoke runs L3 and L4 passed as the criterion states, so this is not a gap against AC-3."],"items":[{"ac":"AC-1","status":"proven","evidence":"Clause table rows for AC-1. Condition: test_cwd_names_the_project plus live runs L1-L4. Boundary: live runs launched in an empty /tmp/acp-smoke-launch-* folder. Negative: test_a_cwd_that_does_not_exist_is_an_error (launch never called). Mapping rows S2.1, S2.3, S7.1."},{"ac":"AC-2","status":"proven","evidence":"TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches (S1.1/S1.2). Live runs L1-L4 with --launch-timeout 60, replies in 0.4-0.7 s, with and without a pod (S1.3)."},{"ac":"AC-3","status":"proven","evidence":"Live runs L1 (claude, no pod), L2 (claude, pod up), L3 (omp, pod up), L4 (omp, no pod), all with --no-path from a different directory. Negative: tools/acp-smoke.py main() final drain, with 'PASS: every stdout byte parsed as JSON-RPC' printed in each run. Mapping rows S7.1, S7.2, S4.7."},{"ac":"AC-4","status":"proven","evidence":"Manual Atlas run S8.1: one proxy process 3125599 served two projects, with two docker exec children and each session reporting its own pwd. Also test_a_second_project_gets_its_own_agent and live L1/L2. Negative: S8.2 pinned entry with cwd as the worktree ran in .../harnessed/main, plus TestThePathArgumentWins::test_path_beats_cwd."},{"ac":"AC-5","status":"proven","evidence":"Live runs L1-L4 show no drift line, and a drift line fails the run. Pinned versions are named: claude-agent-acp 0.85.1 for L1/L2 and omp 18.6.1 for L3/L4. Negative: test_s5_3_a_drift_line_fails_the_run and TestDrift::test_a_differing_reply_is_reported_per_field. Mapping rows S5.1, S5.3."},{"ac":"AC-6","status":"proven","evidence":"TestSessionList::test_before_any_session_the_list_is_empty (existing cwd, no launch, fresh serve as restart). test_with_the_projects_agent_running_it_answers (the agent's own reply). test_a_bad_cwd_is_never_an_error (no error reply). Mapping rows S10.1-S10.4."}]}
```
