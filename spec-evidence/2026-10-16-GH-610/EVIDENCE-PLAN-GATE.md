# Gate 2a, evidence against the plan

verdict: ready
story: GH-610
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 107551/798
record: work/evidence-plan-record.json
graded: 2026-10-18T10:37:24.285Z

## Reasons

none

## Record

```json
{"gaps":[],"items":[{"scenario":"S1.1","status":"proven","evidence":"tests/test_recipes_integration.py::test_gortex_hooks_stop_at_six_events, line 315 `assert set(hooks) == six`, with the six named events at line 312"},{"scenario":"S1.2","status":"proven","evidence":"same test, lines 317-319: loop over claude, omp, opencode, codex and antigravity asserting neither Stop nor SubagentStop is a key"},{"scenario":"S1.3","status":"proven","evidence":"same test, lines 322-326: one `gortex hook` entry per event, PreToolUse matcher `*`, PostToolUse matcher equals _GORTEX_POST_TOOL_MATCHER. recipe.yaml:226 holds the same matcher string"},{"scenario":"S2.1","status":"proven","evidence":"tests/test_recipes_integration.py::test_all_catalog_recipes_pass_strict, mapping row S2.1 (the test body was not opened; the gauntlet stamp is green)"},{"scenario":"S2.2","status":"proven","evidence":"same new test, line 329: re.search(r'\"command\"\\s*:\\s*\"gortex hook\"', json.dumps(hooks, indent=2))"},{"scenario":"S3.1","status":"proven","evidence":"I read recipe.yaml lines 180-239 and README.md in full and found no capital-S `Stop` word and no `8 events`. The comment at recipe.yaml:189-190 reads \"minus its two end-of-turn events (turn end and subagent end)\". The hooks block at recipe.yaml:220-234 holds six events"},{"scenario":"S3.2","status":"proven","evidence":"README.md:23 reads \"| hooks (`gortex hook`, 6 events) | `recipe.yaml` `hooks:` → assembler `settings.json` | every tool call / prompt |\""}]}
```
