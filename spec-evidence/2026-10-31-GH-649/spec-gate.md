# Gate 1a, spec readiness

verdict: not-ready
story: GH-649
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 78345/1225
record: work/spec-record.json
graded: 2026-10-31T13:54:49.956Z

## Reasons

- finding 1: PR-REFERENT: Say in the plan what the brief is and what phases 1, 5 and 6 are, or name the spike's steps and drop the phase numbers. The same applies to "phase 6 of the brief" in Documentation.
- finding 2: PR-REFERENT: Define the stack tool bin dir in Terms, for example as the directories S1.6 builds from the stack's `tools:` entries, and say how they are found.

## Record

```json
{"input":"Plan","gaps":["prompt 3: S3.5 and the Summary disagree on `--off` when a harnessed plugin is enabled at the other scope, because `--off` without `--global` is only specified for local scope.","prompt 3: S3.12 says installs run with `home=<plugin>`, but Known limits says `setup:` and `init:` run against the host-run home, so an implementer may not know which scripts count as install scripts."],"deferred":[],"findings":[{"rule":"PR-REFERENT","quote":"Precondition for `/spec-evidence:build`: phase 1 of the brief, the manual spike, has passed.","smallest_fix":"Say in the plan what the brief is and what phases 1, 5 and 6 are, or name the spike's steps and drop the phase numbers. The same applies to \"phase 6 of the brief\" in Documentation."},{"rule":"PR-REFERENT","quote":"a stack tool bin dir that holds an executable `srv`","smallest_fix":"Define the stack tool bin dir in Terms, for example as the directories S1.6 builds from the stack's `tools:` entries, and say how they are found."}]}
```
