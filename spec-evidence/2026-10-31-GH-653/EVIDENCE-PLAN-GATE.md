# Gate 2a, evidence against the plan

verdict: ready
story: GH-653
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 77562/1125
record: work/evidence-plan-record.json
graded: 2026-10-31T18:15:50.390Z

## Reasons

none

## Record

```json
{"gaps":["The report ran no full gauntlet and has no recorded baseline. It also lists the manual rerun of the issue's command as still open. A separate layer covers these, and they do not change the per-scenario grades.","I did not open the test file. The report names the test ids and does not cite path:line, so each grade rests on the mapping rows alone."],"items":[{"scenario":"S1.1","status":"proven","evidence":"tests/test_use.py::TestStackMiseEnv::test_s1_1_install_scripts_see_the_stack_mise_variables, mapping row S1.1, pass"},{"scenario":"S1.2","status":"proven","evidence":"tests/test_use.py::TestStackMiseEnv::test_s1_2_install_path_begins_with_the_stack_tool_prefix, mapping row S1.2, pass"},{"scenario":"S1.3","status":"proven","evidence":"tests/test_use.py::TestStackMiseEnv::test_s1_3_no_user_mise_variables_still_gives_the_stack_ones, mapping row S1.3, pass"},{"scenario":"S2.1","status":"proven","evidence":"tests/test_use.py::TestStackMiseEnv::test_s2_1_the_user_values_come_back, mapping row S2.1, pass. A mutant with no restore failed it."},{"scenario":"S2.2","status":"proven","evidence":"tests/test_use.py::TestStackMiseEnv::test_s2_2_every_claude_plugin_call_sees_the_user_values, mapping row S2.2, pass. A mutant with no restore failed it."},{"scenario":"S2.3","status":"proven","evidence":"tests/test_use.py::TestStackMiseEnv::test_s2_3_a_failed_install_still_restores_the_user_values, mapping row S2.3, pass. A mutant with no restore failed it."}],"decisions":[{"id":"A1","status":"complete"},{"id":"A2","status":"complete"},{"id":"A3","status":"complete"}]}
```
