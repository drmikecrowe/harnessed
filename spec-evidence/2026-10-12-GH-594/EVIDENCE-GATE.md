# Gate 2, evidence

verdict: ready
story: GH-594
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 66812/216
record: work/evidence-record.json
graded: 2026-10-13T19:25:46.668Z

## Reasons

none

## Record

```json
{"gaps":["The story's criteria name no @SC tag, so I graded each from the report's 'Story criteria, by clause' table and the Spec to Test mapping. The mapping cites test ids, not path:line, so I opened no cited file and graded the test ids as named.","The report itself says the live layer was not run (UNAVAILABLE until the PR) and that adversarial review and mutation were substituted. These do not change any item above.","The manual API-key evidence for AC-2 uses a dummy key and 'approved' holding 20 zeros. The criterion's negative (a declined key stays declined) rests on unit tests only (rejected: [\"def\"] kept unchanged)."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows S2.1 (container: test_s2_1_first_launch_seeds_trust_for_the_project), S3.1 (host: test_s3_1_first_launch_takes_identity_and_trust_but_not_host_state), S3.7, and S4.1 manual run of both paths. Negative covered by S1.1 (no customApiKeyResponses in the owned shape) and S1.5."},{"ac":"AC-2","status":"proven","evidence":"Condition: S1.2, S2.2 (container), S3.2 (host), and S4.1 API key manual run on both paths, including a real container relaunch. Boundary: S2.2 and S3.2. Negative: S1.2, S2.2 and S3.2 keep rejected: [\"def\"] unchanged."},{"ac":"AC-3","status":"proven","evidence":"Condition and boundary: test_s2_2_answers_in_the_stub_survive_a_relaunch (container), test_s3_2_in_stack_answers_survive_a_relaunch (host), and the S4.1 container stub that kept Claude's session keys. Negative: test_s1_3_onboarding_is_forced_true."},{"ac":"AC-4","status":"proven","evidence":"Condition: S1.7, S1.9, test_s3_4_isolated_auth_keeps_host_identity_out. Boundary: test_claude_container_auth.py::TestIsolatedAuthDoesNotLeakHostAccountMetadata::test_isolated_seed_omits_account_identity (container) and test_s3_4_host_backend_carries_isolated_auth_into_the_seed (host). Negative (isolated_auth off): S1.6 and S3.1."},{"ac":"AC-5","status":"proven","evidence":"Condition: S1.5, S3.1, test_s3_10_a_legacy_copy_loses_the_users_mcp_servers. Boundary (host path): S3.1 and S3.10. Negative (the stack's own servers still load): test_s3_8_the_stacks_servers_load_and_the_users_do_not."}]}
```
