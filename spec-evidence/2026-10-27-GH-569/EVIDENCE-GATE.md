# Gate 2, evidence

verdict: ready
story: GH-569
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 113952/2744
record: work/evidence-record.json
graded: 2026-10-27T14:39:49.458Z

## Reasons

none

## Record

```json
{"gaps":["The VS Code panel, Zed panel and Atlas list are unverified (manual row). S4.6 only calls the registered wrapper the way the extension does.","S1.1, S1.5 and S1.6 stub aoe.sync_session. The AC-1 row semantics (one row, no duplicate, repair of a pre-change row) rest on older tests, and test_aoe_real skips in CI.","The live and live-docker jobs have not run. Real execution is substituted: _build_stack was never run for real, so the build-first path (AC-7) is covered by stubs and by S7.5 only.","Review risk: a host register run on a machine with no container runtime and a missing or stale profile fails in _build_stack, although host-run itself would assemble in-process. No mapped test covers this.","No criterion names an @SC tag. I joined each criterion clause to the scenarios in the 'Story criteria, clause by clause' table and the mapping rows. I could not check the cited test files, because the mapping gives test ids and no path:line."],"items":[{"ac":"AC-1","status":"proven","evidence":"S1.1 (one row, local launcher, exit 0, agent not started), S1.2 to S1.4 (second run adds no row, pre-change row recognised and repaired, via test_aoe.py and test_aoe_real.py), S1.5 (no aoe: says so, non-zero, writes nothing)"},{"ac":"AC-2","status":"proven","evidence":"S2.1 (agent_servers entry with the ACP launcher), S2.2 (second run changes no byte), S2.3 (only the entry's lines change, comments survive), S2.6 (invalid JSON refused, file left as it was)"},{"ac":"AC-3","status":"proven","evidence":"S3.1 (Atlas entry with the ACP launcher), S3.2 (other entries keep their bytes), S3.3 (missing directory and file created), S3.4 (invalid JSON refused)"},{"ac":"AC-4","status":"proven","evidence":"S4.1 and S4.4 (wrapper setting is the claude launcher), S4.6 (wrapper called as the extension calls it starts the stack's claude), S4.2 (second stack replaces the one value, rest unchanged), S4.3 (non-claude harness refused)"},{"ac":"AC-5","status":"proven","evidence":"S5.1 (overlay integration runs), S5.2 (overlay wins over repo catalog), S5.3 (unknown name lists the available integrations and builds nothing)"},{"ac":"AC-6","status":"proven","evidence":"S6.1 (normal launch registers nothing; test_adhoc_launch_is_not_persisted), S6.2 (test_aoe.py TestForgetStack removes the stack's aoe rows), S6.3 (no aoe integration in any root is an unknown name that lists the available ones)"},{"ac":"AC-7","status":"proven","evidence":"S7.1 and S7.2 (missing or stale profile builds before the integration), S7.5 (after build and zed, the ACP launcher answers initialize), S7.3 (current profile, no build), S7.4 (failed build runs no integration)"}]}
```
