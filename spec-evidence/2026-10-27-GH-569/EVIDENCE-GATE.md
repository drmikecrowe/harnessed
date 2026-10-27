# Gate 2, evidence

verdict: not-ready
story: GH-569
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 113715/3188
record: work/evidence-record.json
graded: 2026-10-27T14:23:16.490Z

## Reasons

- AC-4: unproven
- AC-7: unproven

Work list, unproven: AC-4, AC-7

## Record

```json
{"gaps":["AC-4: the Claude Code panel running claude through the stack (S4.6) is a manual check the report marks unverified.","AC-7: the ACP `initialize` reply with a `\"result\"` after a register run (S7.5) is a manual check the report marks unverified.","AC-2 and AC-3: the Zed panel and Atlas list showing the entry are manual and unverified. The criteria's testable clauses are covered, so these are not graded against them.","AC-1: the second-run and pre-change-row clauses rest on tests that predate this change (test_aoe.py, test_aoe_real.py). test_aoe_real skips in CI.","Review risk in the report: on a host-only machine, a register run with a missing or stale profile needs a container runtime for the build. This bears on AC-7's build-first clause."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows S1.1 (ti::TestAoeRegister::test_s1_1_one_row_and_the_local_launcher), S1.2 to S1.4 (test_aoe.py::TestWriteDispatch, TestCommandDrift, test_aoe_real.py), S1.5 (ti::TestAoeRegister::test_s1_5_no_aoe_writes_nothing and test_s1_5_end_to_end_without_aoe). They cover the condition, the one-row and repair boundary, and the no-aoe negative."},{"ac":"AC-2","status":"proven","evidence":"Mapping rows S2.1 (ti::TestZed::test_s2_1_the_entry_runs_the_acp_launcher), S2.2 and S2.3 (second run changes no byte, comments survive, tj::test_the_edit_lands_and_every_comment_survives), S2.6 (invalid JSON refused, file left as it was)."},{"ac":"AC-3","status":"proven","evidence":"Mapping rows S3.1 (ti::TestAtlas::test_s3_1_the_entry_runs_the_acp_launcher), S3.2 (other entries keep their bytes), S3.3 (missing file created), S3.4 (invalid JSON refused)."},{"ac":"AC-4","status":"unproven","evidence":"S4.1, S4.2, S4.3 and S4.5 cover the setting value, the replace-one-value boundary, the omp refusal and invalid JSON. The clause 'the Claude Code panel in VS Code then runs claude through that stack' maps to S4.6, which is 'manual ... unverified'. Clause table: 'AC-4 condition: the Claude Code panel then runs claude through the stack | S4.6 | unverified'."},{"ac":"AC-5","status":"proven","evidence":"Mapping rows S5.1 (ti::TestRunner::test_s5_1_the_contract_reaches_the_integration), S5.2 (overlay wins over repo catalog), S5.3 (unknown name lists the available integrations, builds nothing)."},{"ac":"AC-6","status":"proven","evidence":"Mapping rows S6.1 (ti::TestNoAutomaticRegistration::test_s6_1_a_normal_launch_registers_nothing), S6.2 (test_aoe.py::TestForgetStack::test_removes_every_harness_of_the_named_stack), S6.3 (ti::TestNoAutomaticRegistration::test_s6_3_no_aoe_integration_in_any_root_is_an_unknown_name)."},{"ac":"AC-7","status":"unproven","evidence":"S7.1 and S7.2 (build first), S7.3 (no build when current) and S7.4 (failed build runs nothing) are mapped. The clause that the ACP launcher answers `initialize` with a `\"result\"` maps to S7.5, which is 'manual ... unverified'. Clause table: 'AC-7 condition: the ACP launcher then answers initialize with a result | S7.5 | unverified'."}]}
```
