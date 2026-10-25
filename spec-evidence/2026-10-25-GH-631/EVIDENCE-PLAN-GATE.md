# Gate 2a, evidence against the plan

verdict: ready
story: GH-631
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 75582/1891
record: work/evidence-plan-record.json
graded: 2026-10-25T12:13:59.405Z

## Reasons

none

## Record

```json
{"gaps":["The `live` and `live-docker` CI jobs are not run. The report states this, and the SPEC verification contract requires both on the PR.","The report names no test for the busy path when the profile directory has been deleted (adversary hunch 1). No SPEC scenario asks for one.","I did not open the test files. I graded each scenario on its named test id and the stamp, which shows tests, coverage, types, lint, shellcheck and secrets green on commit 61184e7."],"items":[{"scenario":"S1.1","status":"proven","evidence":"tests/test_profile_claim.py::TestConcurrentLaunchesBuildOnce::test_s1_1_two_racing_claims_both_succeed_and_build_once, mapping row S1.1, tests layer green"},{"scenario":"S1.2","status":"proven","evidence":"tests/test_profile_claim.py::TestConcurrentLaunchesBuildOnce::test_s1_2_the_second_claim_prints_the_in_use_line_once, mapping row S1.2"},{"scenario":"S2.1","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s2_1_a_live_sessions_profile_is_reused_not_reset, mapping row S2.1"},{"scenario":"S2.2","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s2_2_a_reused_profile_gets_no_settings_merge, mapping row S2.2"},{"scenario":"S3.1","status":"proven","evidence":"tests/test_profile_claim.py::TestAfterEverySessionEnds::test_s3_1_a_killed_session_releases_the_profile, mapping row S3.1"},{"scenario":"S3.2","status":"proven","evidence":"tests/test_profile_claim.py::TestAfterEverySessionEnds::test_s3_2_a_first_claim_creates_the_dir_and_both_lock_files, mapping row S3.2"},{"scenario":"S4.1","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s4_1_a_failed_build_releases_the_locks, mapping row S4.1"},{"scenario":"S4.2","status":"proven","evidence":"tests/test_profile_claim.py::TestFailedBuildReleases::test_s4_2_a_builder_that_dies_hands_the_build_to_the_waiter, mapping row S4.2"},{"scenario":"S5.1","status":"proven","evidence":"tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_1_the_session_lock_is_held_after_exec, mapping row S5.1"},{"scenario":"S5.2","status":"proven","evidence":"tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_2_killing_the_execd_process_releases_it, mapping row S5.2"},{"scenario":"S5.3","status":"proven","evidence":"tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_3_the_gate_fd_does_not_reach_the_execd_process, mapping row S5.3"},{"scenario":"S6.1","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s6_1_host_run_and_host_acp_each_claim_once, mapping row S6.1"},{"scenario":"S6.2","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s6_2_project_setup_never_claims, mapping row S6.2"},{"scenario":"S7.1","status":"proven","evidence":"tests/test_profile_claim.py::TestLockFilesOutliveAReset::test_s7_1_reset_profile_leaves_both_lock_files, mapping row S7.1"}],"decisions":[{"id":"A1","status":"complete"}]}
```
