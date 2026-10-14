# Gate 1a, spec readiness

verdict: not-ready
story: GH-604
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 66254/19
record: work/spec-record.json
graded: 2026-10-14T11:48:15.361Z

## Reasons

- finding 1: PR-SCOPE: Say which AC-4 clause S5.6 serves, or drop it. AC-4's negative case covers only an unrecognised copy that still answers first.
- finding 2: PR-REFERENT: Quote the failed-install warning's text here, or name the test that pins it, so the scenario does not rely on the builder having read the current code.

## Record

```json
{"input":"Plan","gaps":["prompt 2: S5.6 builds a warning for 'adapter not on PATH after the install', which no AC asks for. AC-4's negative case covers only a different copy answering first.","prompt 3: S5.5 says 'the existing failed-install warning' without giving its text. A builder who has not read launcher.py cannot tell what the test must match.","prompt 3: Decide 2 skips the re-check for the mise command, so the AC-4 negative case ('check again right after the install') is not covered for mise. The plan states this openly in S5.3 and Known limits, so it is advice, not a finding."],"deferred":[{"ac":"AC-3","heading":"S3. A pnpm-installed adapter gets the pnpm command"}],"findings":[{"rule":"PR-SCOPE","quote":"S5.6 (negative) Given the S4 setup, when the install exits 0 and no `claude-agent-acp` is on PATH afterward, then `build` prints one warning that says the adapter is not on PATH, and exits 0.","smallest_fix":"Say which AC-4 clause S5.6 serves, or drop it. AC-4's negative case covers only an unrecognised copy that still answers first."},{"rule":"PR-REFERENT","quote":"then `build` prints the existing failed-install warning, prints no shadow warning, and exits 0.","smallest_fix":"Quote the failed-install warning's text here, or name the test that pins it, so the scenario does not rely on the builder having read the current code."}]}
```
