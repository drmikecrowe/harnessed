# Gate 1a, spec readiness

verdict: not-ready
story: GH-582
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 69964/431
record: work/spec-record.json
graded: 2026-10-12T12:01:55.056Z

## Reasons

- finding 1: PR-REFERENT: Define how the test produces the staged deletion. The stub `harnessed` only copies files over the tree, so add a `$STUB_DIR/deletes` list the stub removes, or name the file the test deletes and how.

## Record

```json
{"input":"Plan","gaps":["prompt 1: The story never says how a human learns the PR exists, and the plan adds no notification (the Gate 1 record raised this); nothing else in the story is left uncovered.","prompt 2: The plan builds a merged-PR skip (S3.5), a `--no-rebuild` flag, a rewrite of the preflight.sh header comment and a CLAUDE.md edit; all trace to AC-3, AC-5 or AC-4, so they are noted here and not raised as findings.","prompt 3: The story constraint says harness pins keep their 2-day window, but Terms (Eligible bump) applies a harness release younger than 2 days at any age, so a builder reading the story and the plan could ship either; the plan records this as Decide 2 A, so state in one sentence that it overrides the story constraint.","prompt 3: S3.1 requires a checkout of `origin/upgrade-<date>` before `harnessed` runs, but the stub log holds only `gh` and `harnessed` argv lines, so a builder cannot tell how a test observes that order."],"deferred":[{"ac":"AC-1","heading":"Terms"},{"ac":"AC-5","heading":"S5. No prompt, no rebuild (AC-5)"}],"findings":[{"rule":"PR-REFERENT","quote":"S2.5 (negative, safety guard for AC-2: the API commit in Terms carries additions only, so a deletion would be dropped silently) Given a staged change that deletes a file under `catalog/`, when the run runs","smart_fix_placeholder":"","smallest_fix":"Define how the test produces the staged deletion. The stub `harnessed` only copies files over the tree, so add a `$STUB_DIR/deletes` list the stub removes, or name the file the test deletes and how."}]}
```
