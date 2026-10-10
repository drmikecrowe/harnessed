# Gate 2, evidence

verdict: ready
story: GH-571
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 69860/221
record: work/evidence-record.json
graded: 2026-10-10T20:50:18.283Z

## Reasons

none

## Record

```json
{"gaps":["AC-5 is proven by argv-level tests (S5.1, S5.2, S5.3). The report shows no real claude session loading or not loading a project .mcp.json.","AC-4 'host-run runs the same verb' rests on e8cdfd9, which had no adversary review (NOT RUN, stated in the report).","Mutation layer not run; live.yml layer not run yet; fresh-wheel install of the claude wrapper path not exercised.","The omp half of AC-2 and AC-8 ran on stack hostspike, not gortex-ghissues (SPEC Revision 7)."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows S1.1/S1.3 (stdout clean for omp and claude), S1.2 'launch_and_init_output_go_to_stderr' (boundary), S1.5 'harness_without_acp_is_refused_before_any_work' (negative, opencode exit 2); AC-1 condition/boundary/negative rows"},{"ac":"AC-2","status":"proven","evidence":"S2.1 smoke logs: claude initialize in 6.7s (smoke-host-acp-claude.log:18), omp in 5.1s (smoke-host-acp-omp.log:16), with --launch-timeout 60; S2.2 'unbuilt_stack_names_the_build_command' asserts exit 1, empty stdout, build command on stderr"},{"ac":"AC-3","status":"proven","evidence":"S3.1/S3.2 relay tests, S3.4 --check-cwd smoke logs for omp and claude (folder A then B, one process); negative S3.3 'missing_cwd_is_an_error_and_never_reaches_the_agent' asserts the error and that no setup ran"},{"ac":"AC-4","status":"proven","evidence":"S4.1 (setup before agent sees request), S4.2 (second session does not rerun), S4.5 (host-run and project-setup both enter _launch_host, existing host-run tests pass unchanged), negative S4.3 'failed_setup_is_an_error_naming_the_project' asserts the agent log holds no session/new"},{"ac":"AC-5","status":"proven","evidence":"S5.1 (adapter gets stack MCP file and strict), S5.2 (--no-strict keeps the file, drops strict), S5.3/AC-5 negative test_strict_adds_the_hub_and_strict_before_the_sdk_args (default is strict); evidence is argv-level"},{"ac":"AC-6","status":"proven","evidence":"S6.1 exact question, S6.2 y, S6.3 c, S6.4 n; boundary S6.5 'pinned_version_asks_nothing'; negative S6.8 'missing_adapter_refuses_on_stderr' asserts exit 1, empty stdout, install command on stderr, agent never started"},{"ac":"AC-7","status":"proven","evidence":"S7.1 build writes the launcher for omp and claude, S7.3 uninstall removes it, S7.2 second build leaves one identical launcher, S7.4 no launcher for opencode, antigravity and codex"},{"ac":"AC-8","status":"proven","evidence":"S8.1 smoke-host-acp-omp.log:33 PASS and S8.2 smoke-host-acp-claude.log:65 PASS, started in a new empty folder with no project path in args (AC-8 condition row); S8.3 argv tests"}]}
```
