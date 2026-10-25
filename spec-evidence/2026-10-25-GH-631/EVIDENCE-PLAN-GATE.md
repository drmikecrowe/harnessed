# Gate 2a, evidence against the plan

verdict: ready
story: GH-631
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 75531/1915
record: work/evidence-plan-record.json
graded: 2026-10-25T12:12:59.463Z

## Reasons

none

## Record

```json
{"gaps":["The report marks `live` and `live-docker` as not run here. The plan's verification contract lists them, and they run on the PR.","I did not open the test files. Each mapping row names a test id with status pass, and the gauntlet tests layer is green (4601 passed). I did not run any test.","The report's own review risks are uncovered by any scenario: a profile deleted under a live session by `harnessed build` or `clean`, and no test holding the lock across `_relay_acp` or `subprocess.run`."],"items":[{"scenario":"S1.1","status":"proven","evidence":"tests/test_profile_claim.py::TestConcurrentLaunchesBuildOnce::test_s1_1_two_racing_claims_both_succeed_and_build_once, mapping row S1.1, pass"},{"scenario":"S1.2","status":"proven","evidence":"tests/test_profile_claim.py::TestConcurrentLaunchesBuildOnce::test_s1_2_the_second_claim_prints_the_in_use_line_once, mapping row S1.2, pass"},{"scenario":"S2.1","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s2_1_a_live_sessions_profile_is_reused_not_reset, mapping row S2.1, pass"},{"scenario":"S2.2","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s2_2_a_reused_profile_gets_no_settings_merge, mapping row S2.2, pass"},{"scenario":"S3.1","status":"proven","evidence":"tests/test_profile_claim.py::TestAfterEverySessionEnds::test_s3_1_a_killed_session_releases_the_profile, mapping row S3.1, pass"},{"scenario":"S3.2","status":"proven","evidence":"tests/test_profile_claim.py::TestAfterEverySessionEnds::test_s3_2_a_first_claim_creates_the_dir_and_both_lock_files, mapping row S3.2, pass"},{"scenario":"S4.1","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s4_1_a_failed_build_releases_the_locks, mapping row S4.1, pass"},{"scenario":"S4.2","status":"proven","evidence":"tests/test_profile_claim.py::TestFailedBuildReleases::test_s4_2_a_builder_that_dies_hands_the_build_to_the_waiter, mapping row S4.2, pass"},{"scenario":"S5.1","status":"proven","evidence":"tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_1_the_session_lock_is_held_after_exec, mapping row S5.1, pass"},{"scenario":"S5.2","status":"proven","evidence":"tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_2_killing_the_execd_process_releases_it, mapping row S5.2, pass"},{"scenario":"S5.3","status":"proven","evidence":"tests/test_profile_claim.py::TestSessionLockSurvivesExec::test_s5_3_the_gate_fd_does_not_reach_the_execd_process, mapping row S5.3, pass"},{"scenario":"S6.1","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s6_1_host_run_and_host_acp_each_claim_once, mapping row S6.1, pass"},{"scenario":"S6.2","status":"proven","evidence":"tests/test_host_acp.py::TestTheProfileClaim::test_s6_2_project_setup_never_claims, mapping row S6.2, pass"},{"scenario":"S7.1","status":"proven","evidence":"tests/test_profile_claim.py::TestLockFilesOutliveAReset::test_s7_1_reset_profile_leaves_both_lock_files, mapping row S7.1, pass"}],"decisions":[{"id":"A1","status":"complete"}]}
```
