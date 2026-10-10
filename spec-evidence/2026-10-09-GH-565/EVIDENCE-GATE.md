# Gate 2, evidence

verdict: ready
story: GH-565
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 66716/223
record: work/evidence-record.json
graded: 2026-10-10T11:27:49.592Z

## Reasons

none

## Record

```json
{"gaps":["The story's criteria carry no @SC tags. I joined each AC to scenarios through the Summary's AC-to-scenario list and the Spec to Test mapping rows.","The mapping gives test names only, with no path:line citations, so I did not read any test files. Each proof rests on the test id and its name.","AC-5's boundaries (`harnessed-claude-default.x-container` kept, `harnessed-codex-default-host` kept) are covered only by the name of S5.1, 'only the named pair is removed'. No separate dotted-neighbour or codex test is named.","The report lists the live container layer (`live.yml`) as UNAVAILABLE until the PR. It also substitutes changed-line coverage and scopes mutation testing to the changed functions. These are outside the ACs and do not change any status."],"items":[{"ac":"AC-1","status":"proven","evidence":"S1.1 (install writes three launchers), S1.2 (codex gets no acp launcher), S1.3 (dotted stack, test_s1_3_dotted_stack plus test_global_name_round_trips), S1.4 (build), S1.5 (host-run), S1.6 (container-run), S1.7 (identical launcher not rewritten); mapping rows in EVIDENCE.md"},{"ac":"AC-2","status":"proven","evidence":"S2.1 test_s2_1_cwd_is_the_project, S2.2 test_s2_2_separator_and_agent_flags_pass_through (covers `--` and the arguments after it), S2.3 test_s2_3_no_usable_aoe_leaves_nothing_in_the_project (negative); Summary says these execute the real launcher against a stub harnessed"},{"ac":"AC-3","status":"proven","evidence":"S3.1 test_s3_1_the_local_launcher_execs_the_global_one and test_s3_1_body, S3.2 test_s3_2_aoe_flags_stay_local (boundary), S3.3 test_s3_3_container_acp_writes_no_local_launcher (negative), S3.4 and S3.5 rows"},{"ac":"AC-4","status":"proven","evidence":"S4.1 new-format row removed by rm, S4.2 old --stack row still removed, S4.3 test_s4_3_a_dotted_neighbour_stays (boundary), S4.4 test_s4_4_rm_changes_no_global_launcher (negative: no global launcher deleted); S4.3 also covers other stacks' rows staying"},{"ac":"AC-5","status":"proven","evidence":"S5.1 test_s5_1_only_the_named_pair_is_removed (TestUninstall... and TestRemoveGlobals), S5.2 test_s5_2_referencing_rows_are_named (aoe row paths printed), S5.3 foreign launcher named and kept, S5.4 no rows prints no row path; the dotted and codex boundaries rest on the name of S5.1"},{"ac":"AC-6","status":"proven","evidence":"S6.1 test_s6_1_install_writes_no_old_shim, S6.2 test_s6_2_the_old_shim_is_removed, S6.3 test_s6_3_a_second_uninstall_finds_no_shim (boundary), S6.4 test_s6_4_a_file_that_is_not_the_old_shim_is_kept (negative)"}]}
```
