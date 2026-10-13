# Gate 2a, evidence against the plan

verdict: ready
story: GH-566
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 77835/232
record: work/evidence-plan-record.json
graded: 2026-10-13T11:21:49.273Z

## Reasons

none

## Record

```json
{"gaps":["Live CI (live, live-docker) is unverified because the PR is not open. It is not a numbered scenario, so it does not affect these items.","S8.1 agent replies are reported by the engineer, but the Atlas log lines and ps listing are quoted in the report.","omp two-project --check-cwd live run was not done (claude only). S7.3 is proven on claude by L1 and L2."],"items":[
{"scenario":"S1.1","status":"proven","evidence":"TestInitializeIsAnsweredAtOnce::test_the_reply_is_the_table_entry_and_nothing_launches[omp]"},
{"scenario":"S1.2","status":"proven","evidence":"test_the_reply_is_the_table_entry_and_nothing_launches[claude]; test_every_acp_harness_has_a_canned_reply"},
{"scenario":"S1.3","status":"proven","evidence":"Live runs L1-L4, --launch-timeout 60, replies 0.4-0.7 s"},
{"scenario":"S2.1","status":"proven","evidence":"TestTheProjectComesFromCwd::test_cwd_names_the_project[session/new]"},
{"scenario":"S2.2","status":"proven","evidence":"test_cwd_names_the_project[session/load], [session/resume]"},
{"scenario":"S2.3","status":"proven","evidence":"TestTheProjectComesFromCwd::test_a_cwd_that_does_not_exist_is_an_error"},
{"scenario":"S2.4","status":"proven","evidence":"TestTheProjectComesFromCwd::test_a_missing_or_relative_cwd_is_an_error"},
{"scenario":"S3.1","status":"proven","evidence":"TestThePathArgumentWins::test_path_beats_cwd"},
{"scenario":"S3.2","status":"proven","evidence":"TestThePathArgumentWins::test_the_start_folder_is_the_cwd_the_agent_gets"},
{"scenario":"S3.3","status":"proven","evidence":"TestThePathArgumentWins::test_a_second_cwd_still_goes_to_the_path_project"},
{"scenario":"S4.1","status":"proven","evidence":"test_a_session_before_initialize_still_initializes_the_agent; test_the_agent_gets_the_clients_own_initialize"},
{"scenario":"S4.2","status":"proven","evidence":"TestForwarding::test_later_lines_reach_the_agent_in_order; test_a_raw_line_reaches_the_agent_byte_for_byte"},
{"scenario":"S4.3","status":"proven","evidence":"TestForwarding::test_later_lines_reach_the_agent_in_order; test_a_client_that_closes_at_once_still_gets_its_session"},
{"scenario":"S4.4","status":"proven","evidence":"TestForwarding::test_the_exit_code_is_the_agents[1],[3]; test_every_agent_ends_and_the_first_nonzero_code_wins; test_all_agents_ending_cleanly_exit_zero"},
{"scenario":"S4.5","status":"proven","evidence":"TestForwarding::test_one_agent_exiting_leaves_the_others_working"},
{"scenario":"S4.6","status":"proven","evidence":"Live runs L2 and L3 (pod up: attached, no second pod)"},
{"scenario":"S4.7","status":"proven","evidence":"tests through _check_stdout; Live runs L1-L4 'every stdout byte parsed as JSON-RPC'"},
{"scenario":"S5.1","status":"proven","evidence":"TestDrift::test_a_differing_reply_is_reported_per_field"},
{"scenario":"S5.2","status":"proven","evidence":"TestDrift::test_auth_methods_are_not_drift"},
{"scenario":"S5.3","status":"proven","evidence":"test_acp_smoke.py::test_s5_3_a_drift_line_fails_the_run; Live runs L1-L4 with no drift line"},
{"scenario":"S6.1","status":"proven","evidence":"TestALaunchThatFails (six tests)"},
{"scenario":"S7.1","status":"proven","evidence":"test_s7_1_no_path_container_acp_argv_names_no_project; test_s7_1_no_path_starts_in_a_fresh_folder_and_sends_the_project_as_cwd; Live runs L1-L4"},
{"scenario":"S7.2","status":"proven","evidence":"Live runs L1 (claude, no pod), L2 (claude, pod up), L3 (omp, pod up), L4 (omp, no pod)"},
{"scenario":"S7.3","status":"proven","evidence":"Live runs L1, L2 with --check-cwd /tmp/gh566-smoke-b; each session reported its own folder, proxy 279204 served both"},
{"scenario":"S7.4","status":"proven","evidence":"test_acp_smoke.py::test_s7_4_no_path_with_host_acp_is_a_usage_error"},
{"scenario":"S8.1","status":"proven","evidence":"Manual Atlas run 2026-10-13, proxy 3125599; ps --ppid lists two docker exec children for two projects; agent replies name each project's folder"},
{"scenario":"S8.2","status":"proven","evidence":"Manual Atlas run, pinned entry, proxy 2967442; cwd sent was the worktree, reply 'I'm in .../harnessed/main'"},
{"scenario":"S8.3","status":"proven","evidence":"TestTheProcessIsNamed::test_each_agent_start_names_the_proxy_and_project; Atlas log lines 'harnessed: ACP proxy 3125599: <project>'"},
{"scenario":"S9.1","status":"proven","evidence":"TestSeveralProjects::test_a_second_project_gets_its_own_agent"},
{"scenario":"S9.2","status":"proven","evidence":"test_a_session_id_routes_to_the_agent_that_made_it; test_a_loaded_session_routes_to_its_project; routing property test"},
{"scenario":"S9.3","status":"proven","evidence":"TestSeveralProjects::test_a_slow_launch_does_not_hold_up_another_project"},
{"scenario":"S9.4","status":"proven","evidence":"TestSeveralProjects::test_agent_request_ids_never_collide; property test"},
{"scenario":"S9.5","status":"proven","evidence":"test_one_project_by_any_spelling_is_one_agent[same],[slash],[symlink]"},
{"scenario":"S9.6","status":"proven","evidence":"TestSeveralProjects::test_an_unknown_session_is_an_error"},
{"scenario":"S9.7","status":"proven","evidence":"test_a_request_naming_no_session_is_refused_with_two_agents; test_a_request_naming_no_session_goes_to_the_only_agent"},
{"scenario":"S10.1","status":"proven","evidence":"TestSessionList::test_before_any_session_the_list_is_empty"},
{"scenario":"S10.2","status":"proven","evidence":"TestSessionList::test_with_the_projects_agent_running_it_answers"},
{"scenario":"S10.3","status":"proven","evidence":"TestSessionList::test_no_cwd_uses_the_path_argument; test_no_cwd_and_no_path_is_empty"},
{"scenario":"S10.4","status":"proven","evidence":"TestSessionList::test_a_bad_cwd_is_never_an_error"}
]}
```
