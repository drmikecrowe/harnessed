# Gate 2a, evidence against the plan

verdict: ready
story: GH-637
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 74914/1772
record: work/evidence-plan-record.json
graded: 2026-10-27T12:32:16.387Z

## Reasons

none

## Record

```json
{"gaps":["Test ids were graded as named in the mapping. The report cites no path:line, so I did not open tests/test_claudeauth.py, and I could not check that each test body matches its scenario's Then.","The report notes no test covers the _host_omp_source caller with a marker. SPEC.md has no scenario for it, so it is not a scenario gap."],"items":[{"scenario":"S1.1","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestStackHomeMarkers::test_a_stamped_stack_home_outside_the_data_root_is_not_the_store', RED before the fix, pass; tests layer 4619 passed"},{"scenario":"S1.2","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestStackHomeMarkers::test_an_unstamped_home_with_its_sibling_lock_is_not_the_store', RED before the fix, pass"},{"scenario":"S1.3","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestStackHomeMarkers::test_a_user_dir_with_no_marker_is_honored', mutant '_is_harnessed_owned returns True' killed, pass"},{"scenario":"S1.4","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestStackHomeMarkers::test_a_missing_user_dir_is_honored', same mutant killed, pass"},{"scenario":"S1.5","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestStackHomeMarkers::test_the_refresh_runs_against_the_host_store', RED before the fix, pass"},{"scenario":"S2.1","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_the_lock_and_log_live_under_the_data_root', RED before the fix, pass; mutation _lock_path 3/3 and _log_path 3/3 killed"},{"scenario":"S2.2","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_another_data_roots_refresher_does_not_block_this_one', RED before the fix, pass"},{"scenario":"S2.3","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_another_data_roots_lock_is_left_free', mutant with the fd left open killed, pass"},{"scenario":"S2.4","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_one_refresher_per_data_root', mutant that ignores a held lock killed, pass"},{"scenario":"S2.5","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestRefresherLockPerDataRoot::test_a_stack_config_dir_never_stops_the_start', RED before the fix, pass"},{"scenario":"S3.1","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestOnePassConvertsStackFiles::test_a_stack_file_becomes_a_view', mutant '_REFRESH_KEYS = ()' killed, pass"},{"scenario":"S3.2","status":"proven","evidence":"test 'tests/test_claudeauth.py::TestOnePassConvertsStackFiles::test_an_isolated_pass_keeps_the_refresh_token_in_the_host_store', same mutant killed, pass"}],"decisions":[{"id":"A1","status":"complete"},{"id":"A2","status":"complete"},{"id":"A3","status":"complete"}]}
```
