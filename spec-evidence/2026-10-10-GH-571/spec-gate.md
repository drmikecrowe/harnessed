# Gate 1a, spec readiness

verdict: not-ready
story: GH-571
process: spec-evidence 0.0.1
model: claude-sonnet-5-5
tokens: 70976/436
record: work/spec-record.json
graded: 2026-10-10T16:56:06.203Z

## Reasons

- finding 1: PR-REFERENT: Say how the tests substitute the stub agent for `omp acp` / `claude-agent-acp` and the stub for `[sys.executable, "-m", "harnessed", "project-setup", ...]` (for example a PATH entry or an env var naming the command), since the Terms define the stub agent but not the substitution mechanism.

## Record

```json
{"input":"Plan","gaps":["prompt 1: The story's constraint that the launch folder gets only per-stack setup is covered by S1.4, and every AC has scenarios, so nothing is uncovered.","prompt 2: The new `__main__.py` and the `--check-cwd` flag are not named in any AC, but they serve AC-4 and AC-3/AC-8, so nothing is unasked.","prompt 3: An implementer could build the S4 and S1 tests wrongly because the plan never says how the stub agent and the stub setup verb are swapped in for the real ones, and S5.4's 'the user's own mise variables' does not say which variables."],"deferred":[{"ac":"AC-4","heading":"S4. Per-project setup runs once per project (AC-4)"},{"ac":"AC-8","heading":"S8. The smoke script (AC-8)"}],"findings":[{"rule":"PR-REFERENT","quote":"Given `host-acp` with a stub setup verb that records its args, when the first `session/new` for A arrives, then the stub ran once","smallest_fix":"Say how the tests substitute the stub agent for `omp acp` / `claude-agent-acp` and the stub for `[sys.executable, \"-m\", \"harnessed\", \"project-setup\", ...]` (for example a PATH entry or an env var naming the command), since the Terms define the stub agent but not the substitution mechanism."}]}
```
