# Gate 1a, spec readiness

verdict: not-ready
story: GH-653
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 72874/814
record: work/spec-record.json
graded: 2026-10-31T17:20:19.027Z

## Reasons

- finding 1: PR-REFERENT: Define "the rollback" in the plan: name the function or step in `use` that undoes a failed install, and say whether the restore runs after it.

## Record

```json
{"input":"Plan","gaps":["prompt 3: The Touches section says to restore the user's values in a `finally` after `_host_run_installs` and \"the rollback\", but no scenario or definition says what the rollback is or what triggers it, so an implementer could place the restore before or after it.","prompt 3: S2.2 expects `claude plugin` calls to run with the user's values, but no scenario says whether the plugin emit step, which runs under the stack environment, may call `claude`."],"deferred":[],"findings":[{"rule":"PR-REFERENT","quote":"restore the user's values in a `finally` after `_host_run_installs` and the rollback.","smallest_fix":"Define \"the rollback\" in the plan: name the function or step in `use` that undoes a failed install, and say whether the restore runs after it."}]}
```
