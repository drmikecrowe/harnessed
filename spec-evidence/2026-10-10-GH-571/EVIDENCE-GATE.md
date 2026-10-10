# Gate 2, evidence

verdict: ready
story: GH-571
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 118859/1160
record: work/evidence-record.json
graded: 2026-10-10T23:57:23.478Z

## Reasons

none

## Record

```json
{"gaps":["No criterion names an @SC tag. I joined each AC to the mapping rows by the AC-n condition/boundary/negative rows and the S-ids.","AC-2 and AC-8: the omp run used the `hostspike` stack, not the stack the story names. SPEC Revision 7 records this.","AC-5 negative (a default launch does not load the project's .mcp.json) is proven only through the existing wrapper test for strict being on. No test is named that checks .mcp.json is not loaded.","AC-6 negative: S6.8 asserts exit non-zero, empty stdout and the install command on stderr. The 'asks nothing' part is implied by the refusal and not asserted by name.","The report lists adversary review, mutation and live-layer runs as not run for the last three commits. This does not change the grading of the criteria."],"items":[{"ac":"AC-1","status":"proven","evidence":"S1.1/S1.3 (omp and claude, clean stdout), S1.2 test_s1_2_launch_and_init_output_go_to_stderr (boundary), S1.5 test_s1_5_a_harness_without_acp_is_refused_before_any_work (negative); smoke logs end 'PASS: every stdout byte parsed as JSON-RPC'"},{"ac":"AC-2","status":"proven","evidence":"Read smoke-host-acp-claude.log:18 'ok: initialize answered in 2.8s' and smoke-host-acp-omp.log:16 'ok: initialize answered in 1.9s'. The report says both runs used --launch-timeout 60. Negative: S2.2 test_s2_2_an_unbuilt_stack_names_the_build_command (exit non-zero, empty stdout, build command on stderr)."},{"ac":"AC-3","status":"proven","evidence":"S3.1/S3.2 relay tests; S3.4 smoke --check-cwd. Read claude.log:62,64 and omp.log:30,32, which show 'reported' folders smokeA then smokeB. Negative: S3.3 test_s3_3_a_missing_cwd_is_an_error_and_never_reaches_the_agent (no setup ran, agent log holds no session/new)."},{"ac":"AC-4","status":"proven","evidence":"S4.1 (setup before agent sees request), S4.2 (second session does not rerun, boundary), S4.5 (host-run and project-setup both enter _launch_host, and the six host-run test files pass unchanged), S4.3 (error names the project, agent log has no session/new)."},{"ac":"AC-5","status":"proven","evidence":"S5.1 test_s5_1_the_adapter_gets_the_stack_mcp_file_and_strict (condition), S5.2 test_s5_2_no_strict_keeps_the_file_and_drops_strict (boundary), S5.3 tests/test_acp_verb.py::TestTheClaudeWrapper::test_strict_adds_the_hub_and_strict_before_the_sdk_args (negative, via strict-by-default)."},{"ac":"AC-6","status":"proven","evidence":"S6.1 (exact question), S6.2 (y runs npm install), S6.3 (c runs typed command), S6.4 (n skips), S6.5 (pinned version asks nothing, boundary), S6.8 test_s6_8_a_missing_adapter_refuses_on_stderr (negative)."},{"ac":"AC-7","status":"proven","evidence":"S7.1 test_gh571_s7_1_build_writes_the_host_acp_launcher[omp]/[claude], S7.3 uninstall removes, S7.2 a second build leaves one identical launcher (boundary), S7.4 no launcher for opencode/antigravity/codex (negative)."},{"ac":"AC-8","status":"proven","evidence":"S8.1 and S8.2 smoke logs, last line of each 'PASS: every stdout byte parsed as JSON-RPC'. The 'run:' line 1 of each shows a /tmp/acp-smoke-launch-* folder and no project path in the argv. S8.3 test_s8_host_acp_argv_names_no_project."}]}
```
