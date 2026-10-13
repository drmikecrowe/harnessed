# Gate 2, evidence

verdict: not-ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 70040/228
record: work/evidence-record.json
graded: 2026-10-13T11:02:58.324Z

## Reasons

- AC-6: unproven

Work list, unproven: AC-6

## Record

```json
{"gaps":["AC-6: the report reads 'the project's pod is running' as 'this process runs an agent for the project' (Decide 4). The story says pod. A pod that is up but has no agent in this proxy process gets an empty list under the report's reading, and nothing shows the request reaching that pod. Only unit tests cover AC-6, and no live or Atlas run does.","Live CI (live, live-docker) is unverified, as the report admits. The criteria do not name it.","AC-4 shows the agent reporting a host-style path, e.g. /home/mcrowe/.../infrastructure. The report does not show that this equals paths.container_project_path for that project. I accepted it because the docker exec -w arguments match.","The story criteria carry no @SC tags, so I graded each AC from the report's clause-by-clause table. No tag joins were made."],"items":[{"ac":"AC-1","status":"proven","evidence":"Clause rows cite test_acp_proxy.py::TestTheProjectComesFromCwd::test_cwd_names_the_project and ::test_a_cwd_that_does_not_exist_is_an_error (launch never called). Live runs L1-L4 started in an empty /tmp folder."},{"ac":"AC-2","status":"proven","evidence":"TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches covers the negative. Live runs L1-L4 give replies in 0.4-0.7 s with --launch-timeout 60, with no pod (L1, L4) and with the pod up (L2, L3)."},{"ac":"AC-3","status":"proven","evidence":"Live runs L1 (claude, no pod), L2 (claude, pod up), L3 (omp, pod up) and L4 (omp, no pod) all print PASS. The non-JSON stdout negative is covered by tools/acp-smoke.py main() final drain and the S4.7 _check_stdout tests."},{"ac":"AC-4","status":"proven","evidence":"Manual S8.1: one proxy process (3125599) served two projects, with docker exec -w for each project and the agent's pwd replies. Manual S8.2: the pinned path /a beat cwd /b (proxy 2967442). Also TestThePathArgumentWins::test_path_beats_cwd and TestSeveralProjects::test_a_second_project_gets_its_own_agent."},{"ac":"AC-5","status":"proven","evidence":"Live runs L1-L4 show no drift line, and a drift line fails the run (test_acp_smoke.py::test_s5_3_a_drift_line_fails_the_run). The versions were claude-agent-acp 0.85.1 and omp 18.6.1. TestDrift::test_a_differing_reply_is_reported_per_field covers the negative."},{"ac":"AC-6","status":"unproven","evidence":"Cited tests: TestSessionList::test_before_any_session_the_list_is_empty, ::test_with_the_projects_agent_running_it_answers and ::test_a_bad_cwd_is_never_an_error. They test 'agent running in this process', not 'pod running', which the report's own Decide 4 admits. The pod-up case is not shown to reach the pod, and no live evidence exists."}]}
```
