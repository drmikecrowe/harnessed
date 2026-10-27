# Gate 1a, spec readiness

verdict: not-ready
story: GH-637
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 68793/1553
record: work/spec-record.json
graded: 2026-10-27T10:49:52.090Z

## Reasons

- finding 1: PR-CONTEXT: Replace the reference to "the brief" with the stated reason the sibling `<name>.lock` file counts as a stack-home marker, in full.
- finding 2: PR-REFERENT: Define what Decide 1 asked and what option A and the other options were, or drop the letter and keep the plain statement.
- finding 3: PR-READINGS: Reconcile with the Orientation `Decide:` line, which still lists "whether the sibling `<harness>.lock` alone is enough proof of a stack home; whether two refreshers for one host store are safe during an upgrade": move both to Decided, citing the Known limits, or mark them open.
- finding 4: PR-REFERENT: Define `<data>` (for example `<tmp>/data` with `XDG_DATA_HOME` set to it) and say how the test makes "no refresh due" true (for example the host login's expiry set far in the future).

## Record

```json
{"input":"Plan","gaps":["prompt 3: An implementer could read the Orientation `Decide:` line as two open questions (sibling `.lock` as proof, two refreshers during upgrade) and stall, or as settled by Known limits, while the Summary says no decisions are open; and `<data>` in S3.1 and \"no refresh due\" could be built as different test setups."],"deferred":[],"findings":[{"rule":"PR-CONTEXT","quote":"The brief names that marker; no such layout is known.","smallest_fix":"Replace the reference to \"the brief\" with the stated reason the sibling `<name>.lock` file counts as a stack-home marker, in full."},{"rule":"PR-REFERENT","quote":"Decided: Decide 1, A, lock and log under the data root, governs S2.1 (mcrowe, 2026-10-27).","smallest_fix":"Define what Decide 1 asked and what option A and the other options were, or drop the letter and keep the plain statement."},{"rule":"PR-READINGS","quote":"Open decisions: none. Decide 1 put the lock and log under the data root.","smallest_fix":"Reconcile with the Orientation `Decide:` line, which still lists \"whether the sibling `<harness>.lock` alone is enough proof of a stack home; whether two refreshers for one host store are safe during an upgrade\": move both to Decided, citing the Known limits, or mark them open."},{"rule":"PR-REFERENT","quote":"a stack file `<data>/harnessed/home/s/claude/.credentials.json` holding an older login with `refreshToken`, when `tick()` runs with no refresh due","smallest_fix":"Define `<data>` (for example `<tmp>/data` with `XDG_DATA_HOME` set to it) and say how the test makes \"no refresh due\" true (for example the host login's expiry set far in the future)."}]}
```
