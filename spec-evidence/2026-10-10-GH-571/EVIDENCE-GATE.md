# Gate 2, evidence

verdict: ready
story: GH-571
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 70407/220
record: work/evidence-record.json
graded: 2026-10-10T22:57:35.110Z

## Reasons

none

## Record

```json
{"gaps":["The story's criteria carry no @SC tags. I joined each AC to the report's Spec to Test mapping rows (S-numbered scenarios and the per-AC condition/boundary/negative rows) by content.","AC-5 negative and boundary are shown by argv-level tests (strict flag present or dropped), not by a run that loads or skips a real .mcp.json.","The report itself lists these as not proven: adversary review of e8cdfd9 and 59dc1d5, the mutation layer, live.yml, and a fresh-wheel install of the claude wrapper. These do not change any AC status here."],"items":[{"ac":"AC-1","status":"proven","evidence":"Condition: S1.1 and S1.3 (HA::TestStdoutIsJsonRpcOnly, omp and claude), plus smoke logs. Boundary: S1.2 test_s1_2_launch_and_init_output_go_to_stderr. Negative: S1.5 test_s1_5_a_harness_without_acp_is_refused_before_any_work (opencode, refused before any work)."},{"ac":"AC-2","status":"proven","evidence":"Condition and boundary: S2.1 smoke runs with --launch-timeout 60, claude 3.0 s (smoke-host-acp-claude.log:18) and omp 2.6 s (smoke-host-acp-omp.log:16). Negative: S2.2 HA::TestUnbuiltStack::test_s2_2_an_unbuilt_stack_names_the_build_command, which asserts exit 1, empty stdout and the build command on stderr."},{"ac":"AC-3","status":"proven","evidence":"Condition: S3.1 test_s3_1_each_session_reports_its_own_folder and S3.2. Real agents: S3.4 --check-cwd smoke logs (omp log lines 30,32; claude log lines 62,64). Negative: S3.3 test_s3_3_a_missing_cwd_is_an_error_and_never_reaches_the_agent, which asserts the exact error, that no setup ran, and that the agent got no session/new."},{"ac":"AC-4","status":"proven","evidence":"Condition: S4.1 test_s4_1_the_first_session_runs_setup_before_the_agent_sees_it. Boundary: S4.2 (no rerun for a second session) and S4.5 (host-run and project-setup both enter _launch_host, with the six existing host-run test files unchanged). Negative: S4.3 test_s4_3_a_failed_setup_is_an_error_naming_the_project, which asserts the agent got no session/new."},{"ac":"AC-5","status":"proven","evidence":"Condition: S5.1 test_s5_1_the_adapter_gets_the_stack_mcp_file_and_strict. Boundary: S5.2 test_s5_2_no_strict_keeps_the_file_and_drops_strict. Negative: S5.3 tests/test_acp_verb.py::TestTheClaudeWrapper::test_strict_adds_the_hub_and_strict_before_the_sdk_args, which shows strict by default. Argv-level evidence only; see gaps."},{"ac":"AC-6","status":"proven","evidence":"Condition: S6.1 (exact question), S6.2 (y), S6.3 (c), S6.4 (n). Boundary: S6.5 test_s6_5_the_pinned_version_asks_nothing. Negative: S6.8 HA::TestTheAdapterAtLaunch::test_s6_8_a_missing_adapter_refuses_on_stderr, which asserts exit 1, empty stdout, the install command on stderr, and that the agent never started."},{"ac":"AC-7","status":"proven","evidence":"Condition: S7.1 (omp and claude launcher written by build, in test_launcher_build.py and test_launchscript.py) and S7.3 (uninstall removes it). Boundary: S7.2 test_gh571_s7_2_a_second_build_leaves_one_identical_launcher. Negative: S7.4 for opencode, antigravity and codex."},{"ac":"AC-8","status":"proven","evidence":"S8.1 (omp, smoke-host-acp-omp.log:33, PASS) and S8.2 (claude on gortex-ghissues, smoke-host-acp-claude.log:65, PASS). Both ran from a new empty folder with no project path in the args, per the 'AC-8 condition' row; S8.3 covers the argv with tests/test_acp_smoke.py::test_s8_host_acp_argv_names_no_project."}]}
```
