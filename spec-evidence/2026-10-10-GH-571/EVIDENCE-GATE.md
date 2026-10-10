# Gate 2, evidence

verdict: not-ready
story: GH-571
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 69002/217
record: work/evidence-record.json
graded: 2026-10-10T19:55:55.035Z

## Reasons

- AC-4: unproven

Work list, unproven: AC-4

## Record

```json
{"gaps":["AC-4: the story says host-run runs the same verb. The report's own Honest notes say host-run runs the same four steps at its own call sites and does not call project-setup (Revision 4). The criterion is not met as written.","AC-3 negative and AC-4 negative: the cited test names say 'never reaches the agent' and 'error naming the project'. They do not show that no per-project setup runs after a missing cwd, or that the agent never receives the request after a setup failure. I could not read the tests.","AC-2: the real-agent timing ran on the substituted stack hostspike, not gortex-ghissues. The report discloses this.","AC-2 and AC-6 negatives require nothing on stdout. The cited test names only mention stderr and the build command.","The mutation layer and live.yml are not run. These do not change the proof of any single criterion."],"items":[{"ac":"AC-1","status":"proven","evidence":"S1.1 and S1.3 (stdout JSON-RPC only, omp and claude), S1.2 boundary (launch and init output go to stderr), S1.5 negative (opencode refused before any work), and both smoke logs. All appear as mapping rows."},{"ac":"AC-2","status":"proven","evidence":"S2.1 smoke runs with --launch-timeout 60 (logs smoke-host-acp-omp.log:24 and smoke-host-acp-claude.log:38, stack hostspike) and S2.2 'test_s2_2_an_unbuilt_stack_names_the_build_command'. The AC-2 mapping rows cover condition, boundary and negative."},{"ac":"AC-3","status":"proven","evidence":"S3.1 and S3.2 relay tests. S3.4 --check-cwd smoke logs show omp and claude each reporting folder A, then B. S3.3 'a_missing_cwd_is_an_error_and_never_reaches_the_agent' covers the negative."},{"ac":"AC-4","status":"unproven","evidence":"S4.1 (setup before the agent sees the request), S4.2 (no rerun) and S4.3 (failure is an error naming the project) are mapped. The boundary 'host-run runs the same verb' is met only as 'same steps in the same order' (S4.5). The report's own note says host-run does not call project-setup."},{"ac":"AC-5","status":"proven","evidence":"S5.1 'adapter_gets_the_stack_mcp_file_and_strict', S5.2 'no_strict_keeps_the_file_and_drops_strict', and S5.3 'strict_adds_the_hub_and_strict_before_the_sdk_args'."},{"ac":"AC-6","status":"proven","evidence":"S6.1 (exact question), S6.2 (y), S6.3 (c), S6.4 (n), S6.5 (pinned version asks nothing), S6.7 (no terminal asks nothing and names the command), S6.8 'a_missing_adapter_refuses_on_stderr'."},{"ac":"AC-7","status":"proven","evidence":"S7.1 (omp and claude launcher written), S7.3 (uninstall removes it), S7.2 (second build leaves one identical launcher), S7.4 (opencode, antigravity and codex get none)."},{"ac":"AC-8","status":"proven","evidence":"S8.1 and S8.2: acp-smoke host-acp runs for omp and claude, PASS, from a new empty folder with no project path in the args (log line 1 of each). S8.3 covers argv with no project."}]}
```
