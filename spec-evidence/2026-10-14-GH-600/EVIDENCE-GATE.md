# Gate 2, evidence

verdict: not-ready
story: GH-600
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 68449/236
record: work/evidence-record.json
graded: 2026-10-14T10:04:45.297Z

## Reasons

- AC-3: unproven

Work list, unproven: AC-3

## Record

```json
{"gaps":["AC-3 negative ('a session started before the switch is not required to change') has no evidence. The report marks the clause n-a, so nothing in the report holds it.","Every AC-2 and AC-3 live proof is a log under the gitignored work/ directory. The report quotes the replies, but the logs are not part of the cited evidence. I did not open them or any test file, because the report cites test ids and not path:line."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows S1.1 (CI::TestS1TheFourCommandsAsk::test_s1_1_build, test_s1_1_install, test_s1_1_host_run, test_s1_1_container_run, plus the prompt test), S1.2 boundary (project and parent CLAUDE.md never asked about), S1.3 negative (no import, no question). The report's clause rows for AC-1 condition, boundary and negative also cite the live terminal `harnessed build` prompt."},{"ac":"AC-2","status":"proven","evidence":"Rows S2.3 (live host-acp, tools/acp-smoke.py --prompt, work/s23.log) and S2.4 (live container-acp on docker, work/s24.log, with mount check work/s24-mount.log). Boundary: CI::TestS2CopiesAndTheMount::test_s2_1_y_writes_a_regular_file_with_the_target_bytes and LH::test_s2_1_the_plan_writes_a_regular_copy. Negative: S2.5 (step-0 probe A replied NOT LOADED, plus test_s2_5_no_answer_creates_no_owned_dir)."},{"ac":"AC-3","status":"unproven","evidence":"Condition and boundary are covered: live S3.2 (work/s32.log), LH::test_s3_1_an_unchanged_stack_still_gets_the_new_content, and CI::test_s3_4_container_materialize_refreshes_and_prunes_first. The negative clause is marked 'n-a: no behaviour to test' in the clause table, so no evidence is named for it."},{"ac":"AC-4","status":"proven","evidence":"Rows S4.1 (CI::test_s4_1_s4_2_no_answer_or_n_warns_on_stderr_only[None] and the host-acp process test with JSON-RPC-only stdout), S4.2 ([n]), S4.3 negative (test_s4_3_y_or_i_is_silent). The boundary is checked by `out == \"\"` in the S4 test."},{"ac":"AC-5","status":"proven","evidence":"Rows S5.1 (CI::test_s5_1_the_answer_is_stored_and_not_asked_again, 3 cases), S5.2 boundary (test_s5_2_another_stack_still_asks), S5.3 negative (test_s5_3_n_or_i_copies_nothing)."},{"ac":"AC-6","status":"proven","evidence":"Rows S6.1 (removed import loses its copy), S6.2 (reask answered n or i removes the copies, plus the build --reask-imports test), S6.3 negative (reask answered y deletes nothing), S6.4 (user rule beside the owned dir survives every sync)."},{"ac":"AC-7","status":"proven","evidence":"Rows S7.1 (CI::test_s7_1_a_missing_target_warns_and_the_rest_is_copied and test_s7_1_a_sync_whose_only_target_is_missing_does_not_raise), S7.2 boundary (nested import copied as text, not followed), and the negative row (test_must_not_an_unwritable_copies_dir_warns_and_does_not_raise)."}]}
```
