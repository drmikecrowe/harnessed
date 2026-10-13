# Gate 2, evidence

verdict: not-ready
story: GH-594
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 67345/218
record: work/evidence-record.json
graded: 2026-10-13T18:18:25.923Z

## Reasons

- AC-6: unproven

Work list, unproven: AC-6

## Record

```json
{"gaps":["AC-6: the report says a headless ACP session (host-acp) expands no @-imports, so the gortex active.md import does not load (S4.2 host-acp reply NOT LOADED). container-acp was never run.","AC-6 boundary (an ACP session with no earlier interactive launch) ran in never-seen folders and gave the same NOT LOADED result.","The live layer has not run, because it only runs once a PR exists. Adversarial review was substituted, since its source reads were blocked. The smoke script commit 7f638b2 came after round 2 and was not reviewed. These do not change any per-criterion status."],"items":[{"ac":"AC-1","status":"proven","evidence":"Condition: mapping rows S2.1 (container) and S3.1 (host), S3.7, and the S4.1 trust/import manual run on both paths. Boundary: both paths covered. Negative: s1_1 exact owned shape has no customApiKeyResponses. The example (projects[P] trust keys) is covered by S2.1 and S3.1 seeding trust for the project."},{"ac":"AC-2","status":"proven","evidence":"Condition: s1_2, s2_2, s3_2 and the S4.1 (API key) manual run with relaunch on both paths. Boundary: S2.2 (container) and S3.2 (host). Negative: S1.2, S2.2 and S3.2 keep rejected [\"def\"] unchanged across a relaunch."},{"ac":"AC-3","status":"proven","evidence":"Condition and boundary: s2_2 (container) and s3_2 (host) in-stack answers survive a relaunch. Negative: s1_3_onboarding_is_forced_true."},{"ac":"AC-4","status":"proven","evidence":"Condition: s1_7, s1_9, s3_4_isolated_auth_keeps_host_identity_out. Boundary: test_claude_container_auth.py::test_isolated_seed_omits_account_identity (container) and s3_4_host_backend_carries_isolated_auth_into_the_seed (host). Negative: s1_6 and s3_1 show shared identity comes from the host."},{"ac":"AC-5","status":"proven","evidence":"Condition: s1_5, s3_1, s3_10 (legacy copy loses mcpServers). Boundary: the host path, via S3.1 and S3.10. Negative: s3_8_the_stacks_servers_load_and_the_users_do_not."},{"ac":"AC-6","status":"unproven","evidence":"Mapping rows S4.2 host-acp: fail (NOT LOADED); S4.2 container-acp: unverified. The report states AC-6 is not proven. Only the negative clause is covered, by s3_9_project_setup_seeds_only_the_session_folder, so the condition and boundary are not proven."}]}
```
