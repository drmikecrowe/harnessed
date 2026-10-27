# Gate 1a, spec readiness

verdict: not-ready
story: GH-569
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 77973/1854
record: work/spec-record.json
graded: 2026-10-27T12:22:39.311Z

## Reasons

- finding 1: PR-REFERENT: Change the reference to S1.8; S1.7 is the ACP-launcher scenario and S1.8 is the removal scenario, as the Decided line already says.

## Record

```json
{"input":"Plan","gaps":["prompt 1: The story names no behaviour for a harness an integration does not support beyond the VS Code claude-only case, and the plan fills that in with Zed and Atlas ACP-only refusals, which is reasonable.","prompt 2: The plan refuses the container backend for VS Code (S4.7), the two-flags error (S5.6) and the passthrough rule (S5.7), none of which an acceptance criterion names.","prompt 3: An implementer reading the Orientation 'Decide' line would look for the `--create-aoe-only` removal at S1.7, which is the ACP-launcher scenario, and S4.4 leaves the exact test for 'this is the extension's wrapper call' to the unseen 'argv rule in main'."],"deferred":[{"ac":"AC-1","heading":"S1. aoe (AC-1)"},{"ac":"AC-4","heading":"S4. VS Code (AC-4)"}],"findings":[{"rule":"PR-REFERENT","quote":"`--create-aoe-only` removal (S1.7)","smallest_fix":"Change the reference to S1.8; S1.7 is the ACP-launcher scenario and S1.8 is the removal scenario, as the Decided line already says."}]}
```
