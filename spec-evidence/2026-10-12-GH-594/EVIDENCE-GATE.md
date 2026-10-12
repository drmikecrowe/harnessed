# Gate 2, evidence

verdict: not-ready
story: GH-594
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 67149/218
record: work/evidence-record.json
graded: 2026-10-12T20:45:04.146Z

## Reasons

- AC-6: unproven

Work list, unproven: AC-6

## Record

```json
{"gaps":["AC-6 is not met. The report says the S4.2 host-acp smoke run replied NOT LOADED, so the ACP session does not load the import. container-acp was never run.","The live API key prompt was never observed for AC-1 or AC-2 (the unit tests cover it). The report says this machine's login is a subscription, not an API key.","The live layer has not run, because no PR exists yet.","Adversary review was substituted. Source reads were blocked in both rounds, and commit 7f638b2 came after round 2."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows 'AC-1 condition/boundary/negative'. Tests: test_s2_1_first_launch_seeds_trust_for_the_project (container), test_s3_1_first_launch_takes_identity_and_trust_but_not_host_state and test_s3_7 (host), plus S4.1 manual runs of both paths with no trust or import question. Negative: test_s1_1_empty_inputs_give_exactly_the_owned_shape shows no customApiKeyResponses is written."},{"ac":"AC-2","status":"proven","evidence":"Mapping rows 'AC-2 condition/boundary/negative'. Tests: test_s1_2, test_s2_2_answers_in_the_stub_survive_a_relaunch, test_s3_2_in_stack_answers_survive_a_relaunch. They keep customApiKeyResponses unchanged across a relaunch on both paths, including rejected:[\"def\"] for the declined-key negative. This is unit evidence only; the report marks the live API key half unverified."},{"ac":"AC-3","status":"proven","evidence":"Mapping rows 'AC-3 condition/boundary/negative'. Tests: test_s2_2 and test_s3_2 (answers survive on both paths), test_s1_3_onboarding_is_forced_true (hasCompletedOnboarding reset to harnessed's value)."},{"ac":"AC-4","status":"proven","evidence":"Mapping rows 'AC-4 condition/boundary/negative'. Tests: test_s1_9_isolated_scrubs_host_identity_left_by_a_shared_launch, test_s3_4_isolated_auth_keeps_host_identity_out, and test_claude_container_auth.py::test_isolated_seed_omits_account_identity (container). Negative: test_s1_6_shared_identity_comes_from_the_host and test_s3_1."},{"ac":"AC-5","status":"proven","evidence":"Mapping rows 'AC-5 condition/boundary/negative'. Tests: test_s1_5_host_contributes_nothing_but_identity, test_s3_1, test_s3_10_a_legacy_copy_loses_the_users_mcp_servers. Negative: test_s3_8_the_stacks_servers_load_and_the_users_do_not."},{"ac":"AC-6","status":"unproven","evidence":"The report addresses it and marks it fail. Mapping rows 'AC-6 condition' and 'AC-6 boundary' cite S4.2 host-acp with reply 'NOT LOADED'; container-acp was not run. Only the negative (no other project path is approved, test_s3_9_project_setup_seeds_only_the_session_folder) is shown, so the condition and boundary are not proven."}]}
```
