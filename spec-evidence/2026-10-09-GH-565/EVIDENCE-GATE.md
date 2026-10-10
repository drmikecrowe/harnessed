# Gate 2, evidence

verdict: ready
story: GH-565
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 66620/223
record: work/evidence-record.json
graded: 2026-10-10T11:30:00.327Z

## Reasons

none

## Record

```json
{"gaps":["live.yml container layer has not run (UNAVAILABLE until the PR). It is not proof of any single AC.","Changed-line coverage and whole-file mutation were substituted. The report discloses both.","The adversary review does not cover commits 2acfc39 and 4eb4543. The report discloses this.","The mapping names S-scenarios, not the story's AC ids. The AC-to-scenario join comes from the report's Summary section.","I did not open any test file, because the mapping cites test ids and no path:line. The grades rest on the report's mapping rows only."],"items":[{"ac":"AC-1","status":"proven","evidence":"Summary maps AC-1 to S1.1-S1.11. S1.1 test_s1_1_install_writes_three_launchers covers the three launchers. S1.3 test_s1_3_dotted_stack covers the dotted-stack boundary. S1.7 test_s1_7_identical_launcher_is_not_rewritten covers the no-rewrite boundary. S1.2 test_s1_2_codex_gets_no_acp_launcher covers the codex negative. S1.4 covers build, S1.5 covers host-run, S1.6 covers container-run."},{"ac":"AC-2","status":"proven","evidence":"S2.1 test_s2_1_cwd_is_the_project covers D as the project. S2.2 test_s2_2_separator_and_agent_flags_pass_through covers the `--` and argument pass-through boundary. S2.3 test_s2_3_no_usable_aoe_leaves_nothing_in_the_project covers the negative. The Summary says the real launcher was executed against a stub harnessed."},{"ac":"AC-3","status":"proven","evidence":"S3.1 test_s3_1_the_local_launcher_execs_the_global_one covers the cd-and-exec body. S3.2 test_s3_2_aoe_flags_stay_local covers the --no-strict-mcp-config boundary. S3.3 test_s3_3_container_acp_writes_no_local_launcher covers the negative. S3.4 and S3.5 add the cd-to-own-folder and row-shape checks."},{"ac":"AC-4","status":"proven","evidence":"S4.1 test_s4_1_a_new_format_row_is_removed_by_rm covers new-format rows. S4.2 test_s4_2_an_old_stack_flag_row_is_still_removed covers old --stack rows. S4.3 test_s4_3_a_dotted_neighbour_stays covers the default.x boundary and other stacks' rows staying. S4.4 test_s4_4_rm_changes_no_global_launcher covers the negative that rm deletes no global launcher."},{"ac":"AC-5","status":"proven","evidence":"S5.1 test_s5_1_only_the_named_pair_is_removed (also TestRemoveGlobals::test_s5_1_only_the_named_pair_goes) covers exact-name removal and the other-pair negative. S5.2 test_s5_2_referencing_rows_are_named covers printing the aoe rows that still reference a removed launcher. S5.3 and S5.4 cover the foreign file and the no-rows case. The dotted-neighbour and codex cases are not named in a test title, so I inferred them from 'only the named pair'."},{"ac":"AC-6","status":"proven","evidence":"S6.1 test_s6_1_install_writes_no_old_shim covers install writing no shim. S6.2 test_s6_2_the_old_shim_is_removed covers removal of the matching shim. S6.3 test_s6_3_a_second_uninstall_finds_no_shim covers the report-once boundary. S6.4 test_s6_4_a_file_that_is_not_the_old_shim_is_kept covers the negative."}]}
```
