# Gate 1a, spec readiness

verdict: not-ready
story: GH-631
process: spec-evidence 0.16.2
model: claude-sonnet-5-5
tokens: 70245/1559
record: work/spec-record.json
graded: 2026-10-25T11:20:01.959Z

## Reasons

- finding 1: PR-READINGS: State what release() does to the session lock after done() (for example: still drops it, or also a no-op), and name which one launcher.py relies on.
- finding 2: PR-REFERENT: List the exact functions stubbed as "the materialize steps" and the concrete arguments passed in place of `...`.

## Record

```json
{"input":"Plan","gaps":["prompt 3: An implementer could read \"release() drops both locks; it is a no-op after done() for the gate\" as either keeping or dropping the session lock after done(), and the second reading would silently end the session's protection.","prompt 3: S2.1 stubs \"the materialize steps\" and calls `_launch_host(\"s\", \"claude\", ...)` without saying which steps or which arguments, so two implementers will stub different things."],"deferred":[],"findings":[{"rule":"PR-READINGS","quote":"The claim's `release()` drops both locks; it is a no-op after `done()` for the gate.","smallest_fix":"State what release() does to the session lock after done() (for example: still drops it, or also a no-op), and name which one launcher.py relies on."},{"rule":"PR-REFERENT","quote":"when `_launch_host(\"s\", \"claude\", ...)` runs in-process with `assemble`, `os.execvpe` and the materialize steps stubbed","smallest_fix":"List the exact functions stubbed as \"the materialize steps\" and the concrete arguments passed in place of `...`."}]}
```
