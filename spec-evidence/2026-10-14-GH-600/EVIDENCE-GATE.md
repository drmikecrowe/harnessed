# Gate 2, evidence

verdict: not-ready
story: GH-600
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 67835/234
record: work/evidence-record.json
graded: 2026-10-14T01:41:08.550Z

## Reasons

- AC-2: unproven

Work list, unproven: AC-2

## Record

```json
{"gaps":["AC-2 requires a container-acp session to return the marker. The live container-acp probe (S2.4) did not run, because there was no podman. The report cites only a unit test that the mount is composed. It defers the container proof to the CI live.yml run on the PR, which has not run yet."],"items":[{"ac":"AC-1","status":"proven","evidence":"Mapping rows S1.1 (build, install, host_run and container_run tests, plus the story-prompt test), S1.2 (project and parent CLAUDE.md never asked), S1.3 (no import, no question). Clause table rows for AC-1 condition, boundary and negative cite these tests."},{"ac":"AC-2","status":"unproven","evidence":"The host-acp half is covered by live S2.3 (work/s23.log), the regular-file tests S2.1, and the negative via step-0 probe A (NOT LOADED) and S2.5. The container-acp half is not covered. S2.4 is 'unverified' and the clause row 'AC-2 condition: container-acp returns the marker after y' is marked unverified. Only the mount composition test (S2.2) is cited for it."},{"ac":"AC-3","status":"proven","evidence":"Live S3.2 (gortex instructions switch localization, then a new host-acp session quoted the new line) and S3.1 (refresh on an unchanged stack, rebuilt is False). The boundary is covered by S3.1 and S3.4. The negative clause is a permission, and the report marks it n-a."},{"ac":"AC-4","status":"proven","evidence":"S4.1 and S4.2 (no answer or n warns on stderr, out == ''), the host_acp process test that parses stdout as JSON-RPC only, S4.3 (y or i is silent), S4.4 (no import is silent)."},{"ac":"AC-5","status":"proven","evidence":"S5.1 (answer stored, not asked again), S5.2 (another stack still asks), S5.3 (n or i copies nothing)."},{"ac":"AC-6","status":"proven","evidence":"S6.1 (removed import loses its copy), S6.2 (reask answered n or i removes the copies, plus the build --reask-imports test), S6.3 (reask answered y deletes nothing), S6.4 (a user rule beside the owned dir survives every sync)."},{"ac":"AC-7","status":"proven","evidence":"S7.1 (missing target warns and the rest is copied, and a sync with only a missing target does not raise), S7.2 (nested import copied as text, not followed), and test_must_not_an_unwritable_copies_dir_warns_and_does_not_raise for the never-fails negative."}]}
```
