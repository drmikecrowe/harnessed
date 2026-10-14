# Gate 2, evidence

verdict: ready
story: GH-600
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 68464/237
record: work/evidence-record.json
graded: 2026-10-14T10:12:57.565Z

## Reasons

none

## Record

```json
{"gaps":["AC-2 negative: the live 'NOT LOADED' probe A ran on 0.89.1 before the change existed, not on a stack with the feature present and no stored answer. The unit test test_s2_5 covers that case only at file level.","AC-3 negative is argued from the design (a refresh starts, stops and signals no session) and has no direct test of a session running across the switch.","The live logs under work/ are gitignored and were not opened. The report quotes their replies.","The tests are named without path:line, so I did not open or check them. Grading rests on the report's mapping and its quoted live replies.","AC-7 condition: the mapping does not show that the warning names the missing path."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping S1.1 (test_s1_1_build, _install, _host_run, _container_run, and the exact prompt in the ask test), S1.2 boundary (project and parent never asked), S1.3 negative (no import, no question). The report also quotes the live terminal prompt."},{"ac":"AC-2","status":"proven","evidence":"S2.3 live host-acp and S2.4 live container-acp (docker) both quote text found only in active.md. Boundary: S2.1 tests 'regular file' (test_s2_1_y_writes_a_regular_file_with_the_target_bytes). Negative: S2.5 (test_s2_5_no_answer_creates_no_owned_dir) plus probe A reply NOT LOADED."},{"ac":"AC-3","status":"proven","evidence":"S3.2 live (gortex instructions switch localization, new session quotes the localization-only line). Boundary: S3.1 (test_s3_1_an_unchanged_stack_still_gets_the_new_content, rebuilt is False) and S3.4 (container refresh). Negative: S3.3 and the clause row, which argues a refresh touches no running session."},{"ac":"AC-4","status":"proven","evidence":"S4.1 and S4.2 (no answer and n warn on stderr only), the host-acp process test with stdout parsing as JSON-RPC only and out == \"\", S4.3 (y or i is silent)."},{"ac":"AC-5","status":"proven","evidence":"S5.1 (answer stored, not asked again), S5.2 (another stack still asks), S5.3 (n or i copies nothing)."},{"ac":"AC-6","status":"proven","evidence":"S6.1 (removed import loses its copy), S6.2 (--reask-imports answered n or i removes the copies), S6.3 (reask answered y deletes nothing), S6.4 (user rule beside the owned dir survives every sync)."},{"ac":"AC-7","status":"proven","evidence":"S7.1 (missing target warns and the rest is copied; a sync whose only target is missing does not raise), S7.2 (nested import copied as text, not followed), plus test_must_not_an_unwritable_copies_dir_warns_and_does_not_raise."}]}
```
