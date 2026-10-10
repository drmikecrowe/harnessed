# Gate 2a, evidence against the plan

verdict: ready
story: GH-571
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 131004/644
record: work/evidence-plan-record.json
graded: 2026-10-10T20:50:54.862Z

## Reasons

none

## Record

```json
{"gaps":["Mapping cites test ids only; I did not open the test files, and the report states the tests pass from the gauntlet stamp. This record grades that each scenario is mapped to a named test or log line, not that the tests pass.","Adversarial review of e8cdfd9, the mutation layer and live.yml are reported as not run. They are not scenarios, so they do not change any item.","S2.1 omp half ran on hostspike per SPEC Revision 7, as the SPEC allows."],"items":[
{"scenario":"S1.1","status":"proven","evidence":"HA::TestStdoutIsJsonRpcOnly::test_s1_1_and_s1_3_...[omp], mapping row S1.1"},
{"scenario":"S1.2","status":"proven","evidence":"HA::TestStdoutIsJsonRpcOnly::test_s1_2_launch_and_init_output_go_to_stderr"},
{"scenario":"S1.3","status":"proven","evidence":"HA::TestStdoutIsJsonRpcOnly::test_s1_1_and_s1_3_...[claude]"},
{"scenario":"S1.4","status":"proven","evidence":"HA::TestStdoutIsJsonRpcOnly::test_s1_4_the_launch_folder_gets_no_per_project_setup"},
{"scenario":"S1.5","status":"proven","evidence":"HA::TestStdoutIsJsonRpcOnly::test_s1_5_a_harness_without_acp_is_refused_before_any_work"},
{"scenario":"S2.1","status":"proven","evidence":"smoke-host-acp-claude.log:18 'ok: initialize answered in 6.7s' (gortex-ghissues, claude); smoke-host-acp-omp.log:16 'ok: initialize answered in 5.1s' (hostspike, Revision 7)"},
{"scenario":"S2.2","status":"proven","evidence":"HA::TestUnbuiltStack::test_s2_2_an_unbuilt_stack_names_the_build_command"},
{"scenario":"S3.1","status":"proven","evidence":"HA::TestOneProcessManyProjects::test_s3_1_each_session_reports_its_own_folder"},
{"scenario":"S3.2","status":"proven","evidence":"HA::TestOneProcessManyProjects::test_s3_2_the_agent_gets_each_cwd_unchanged"},
{"scenario":"S3.3","status":"proven","evidence":"HA::TestOneProcessManyProjects::test_s3_3_a_missing_cwd_is_an_error_and_never_reaches_the_agent"},
{"scenario":"S3.4","status":"proven","evidence":"smoke-host-acp-omp.log:30,32 and smoke-host-acp-claude.log:62,64: 'the session in .../smokeA reported .../smokeA' and the same for smokeB"},
{"scenario":"S3.5","status":"proven","evidence":"HA::test_s3_5_concurrent_writers_never_interleave_a_line (hypothesis, 200 examples)"},
{"scenario":"S3.6","status":"proven","evidence":"HA::test_s3_6_every_other_line_is_forwarded_byte_for_byte (hypothesis, 200 examples)"},
{"scenario":"S4.1","status":"proven","evidence":"HA::TestPerProjectSetup::test_s4_1_the_first_session_runs_setup_before_the_agent_sees_it"},
{"scenario":"S4.2","status":"proven","evidence":"HA::TestPerProjectSetup::test_s4_2_a_second_session_in_the_same_project_does_not_rerun_it"},
{"scenario":"S4.3","status":"proven","evidence":"HA::TestFailedSetup::test_s4_3_a_failed_setup_is_an_error_naming_the_project"},
{"scenario":"S4.4","status":"proven","evidence":"HA::TestFailedSetup::test_s4_4_a_failed_project_is_set_up_again_next_time"},
{"scenario":"S4.5","status":"proven","evidence":"HA::TestHostRunSharesTheSetup::test_s4_5_host_run_and_project_setup_run_the_same_steps_in_the_same_order, plus the six named files unchanged in the tests layer"},
{"scenario":"S4.6","status":"proven","evidence":"HA::TestHostRunSharesTheSetup::test_s4_6_project_setup_alone_sets_up_one_project"},
{"scenario":"S5.1","status":"proven","evidence":"HA::TestClaudeMcpAndEnv::test_s5_1_the_adapter_gets_the_stack_mcp_file_and_strict"},
{"scenario":"S5.2","status":"proven","evidence":"HA::TestClaudeMcpAndEnv::test_s5_2_no_strict_keeps_the_file_and_drops_strict"},
{"scenario":"S5.3","status":"proven","evidence":"tests/test_acp_verb.py::TestTheClaudeWrapper::test_strict_adds_the_hub_and_strict_before_the_sdk_args (existing test the SPEC names)"},
{"scenario":"S5.4","status":"proven","evidence":"HA::TestClaudeMcpAndEnv::test_s5_4_the_agent_gets_per_stack_env_only[omp] and [claude]"},
{"scenario":"S6.1","status":"proven","evidence":"BA::TestTheOffer::test_s6_1_a_missing_or_other_version_asks_exactly[None] and [0.84.0]"},
{"scenario":"S6.2","status":"proven","evidence":"BA::TestTheOffer::test_s6_2_yes_runs_the_npm_install"},
{"scenario":"S6.3","status":"proven","evidence":"BA::TestTheOffer::test_s6_3_c_runs_the_typed_command_through_bash"},
{"scenario":"S6.4","status":"proven","evidence":"BA::TestTheOffer::test_s6_4_no_runs_nothing_and_builds_on"},
{"scenario":"S6.5","status":"proven","evidence":"BA::TestTheOffer::test_s6_5_the_pinned_version_asks_nothing"},
{"scenario":"S6.6","status":"proven","evidence":"BA::TestTheOffer::test_s6_6_a_failed_install_warns_and_builds_on"},
{"scenario":"S6.7","status":"proven","evidence":"BA::TestTheOffer::test_s6_7_no_terminal_asks_nothing_and_names_the_command"},
{"scenario":"S6.8","status":"proven","evidence":"HA::TestTheAdapterAtLaunch::test_s6_8_a_missing_adapter_refuses_on_stderr"},
{"scenario":"S6.9","status":"proven","evidence":"BA::TestTheOffer::test_s6_9_omp_never_checks_the_adapter"},
{"scenario":"S6.10","status":"proven","evidence":"HA::TestTheAdapterAtLaunch::test_s6_10_another_version_runs_with_a_warning"},
{"scenario":"S7.1","status":"proven","evidence":"tests/test_launcher_build.py::TestBuildWritesGlobalLaunchers::test_gh571_s7_1_build_writes_the_host_acp_launcher[omp] and [claude]; tests/test_launchscript.py::TestWriteGlobals::test_gh571_s7_1_a_host_acp_launcher_is_written"},
{"scenario":"S7.2","status":"proven","evidence":"tests/test_launcher_build.py::...::test_gh571_s7_2_a_second_build_leaves_one_identical_launcher"},
{"scenario":"S7.3","status":"proven","evidence":"tests/test_launcher_build.py::...::test_gh571_s7_3_uninstall_removes_what_build_wrote"},
{"scenario":"S7.4","status":"proven","evidence":"tests/test_launcher_build.py::...::test_gh571_s7_4_no_host_acp_launcher_without_acp[opencode], [antigravity], [codex]"},
{"scenario":"S8.1","status":"proven","evidence":"smoke-host-acp-omp.log:33 'PASS: every stdout byte parsed as JSON-RPC'; run line 1 shows host-acp omp with no project path, in a temp folder"},
{"scenario":"S8.2","status":"proven","evidence":"smoke-host-acp-claude.log:65 'PASS: every stdout byte parsed as JSON-RPC'; gortex-ghissues, claude"},
{"scenario":"S8.3","status":"proven","evidence":"tests/test_acp_smoke.py::test_s8_3_container_acp_argv_is_unchanged"}
]}
```
