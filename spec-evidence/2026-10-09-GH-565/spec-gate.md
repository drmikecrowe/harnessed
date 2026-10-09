# Gate 1a, spec readiness

verdict: not-ready
story: GH-565
process: spec-evidence 0.0.1
model: claude-sonnet-4-6
tokens: 53125/387
record: work/spec-record.json
graded: 2026-10-09T22:59:22.956Z

## Reasons

- finding 1: PR-REFERENT: Name the specific test functions (or test files) that may be dropped or rewritten directly in this line, so the plan is self-contained without decisions.md.

## Record

```json
{"input": "Plan", "gaps": ["prompt 3: the Must NOT rule and the Touches line both say 'the rewrites decisions.md names' — an implementer who never saw the conversation cannot identify which tests may be dropped or rewritten without reading decisions.md, which is not in the plan"], "deferred": [{"ac": "author-note", "heading": "S3. The local launcher exists only for aoe (AC-3)"}], "findings": [{"rule": "PR-REFERENT", "quote": "Drop the test count below the baseline, except for the tests `decisions.md` names as rewritten.", "smallest_fix": "Name the specific test functions (or test files) that may be dropped or rewritten directly in this line, so the plan is self-contained without decisions.md."}]}
```
